#!/usr/bin/env python3
"""night/edge/fam_japan.py — 系統 japan: 日本株の買いだけ（割安・配当・収益性・勢いの「良い側」を持つ）

事前登録 out/edge_prereg.json の round1_families.japan。読むだけ・門の採点に不使用。

■ 二つの素材（どちらも「その国の株式市場」を相手にする＝同じ通貨・同じ土台）
  F（French 国別）: Ken French の International Countries（MSCI 由来の大型〜中型）。毎年12月末に B/M・E/P・CE/P・D/P で並べ、
     上位30%（High）を時価加重で翌12か月持つ。米ドル建て・配当込み。1975-01〜。相手＝同じファイルの Mkt（Value-Weight・
     All 4 Data Items Not Reqd ＝ h.french_countries と同じ列）。
  J（JKP 日本）: jkpfactors.com の日本の三分位（予言の向きの端 = '3.0'）。毎月組み替え。JKP の 'ret' は米ドルの
     **超過リターン**（米国の短期金利を引いたもの）なので 総リターン = ret + French RF。相手 = JKP 日本の 'mkt'（vw＝上限なしの
     時価加重）+ RF。★確かめたこと（〜2000-12）: JKP 日本 mkt(vw)+RF と French Japan(Dollar) の月次の相関 0.990・平均差 0.04%/月
     ＝同じ土台。vw_cap（上限つき）の市場は相関 0.935 で巨大株を抑える弱い相手なので相手には使わない。
     ⚠ JKP 日本の会計の特徴は 1988-07 まで三分位の銘柄が10社前後しかない（Compustat Global の被覆）ので、三分位の銘柄が
     MIN_N 未満の月は使わない。eqnpo_me（純還元）・fcf_me は 2000-08 まで被覆が無く、選定期間で測れないので候補に入れない。
■ 費用: 片道の回転100%につき 0.25%（事前登録: 個別株の組）。回転は事前登録の置き値＝会計の信号 50%/年・価格の信号 200%/年。
  合成の中の重みの戻し（月ごとに等分へ戻す分）も回転に足す。
■ 先読み: 月 m のリターンは m−1 月末に組まれた組（French は前年12月末・JKP は前月末）の成績で、合成の重みは
  『月 m の組が組まれた時点の銘柄数』（m−1 月末に分かる）だけで決まる。検査は --lookahead。
■ 他の市場での再現: 同じ凍結した規則を French 国別の他の20か国（F）／JKP の同じ20か国（J）へ変えずに当てる。

使い方:
  python3 night/edge/fam_japan.py              → 変種を振って選定期間の表と選ぶ規則を出す（凍結しない）
  python3 night/edge/fam_japan.py --lookahead  → 先読みの検査
  python3 night/edge/fam_japan.py --freeze     → 選んだ規則を out/edge/spec_japan.json に凍結（一度だけ）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h
import csv, io, json, math, statistics as S, subprocess, zipfile
from concurrent.futures import ThreadPoolExecutor

FAMILY = {
    'key': 'japan',
    'name': '日本株の割安・高配当の買いだけ（French 国別・JKP 日本）',
    'implement': ('楽天証券で東証上場の日本株ETFを買う（NISA 成長投資枠の対象・レバレッジ型ではない）。高配当なら '
                  '1489 NEXT FUNDS 日経平均高配当株50・1478 iシェアーズ MSCI ジャパン高配当利回り・1577 NEXT FUNDS 野村日本株高配当70、'
                  '割安なら 1473 系ではなく MSCI Japan Value に連動する投信・ETF（例: 米国上場 EWJV〔iShares MSCI Japan Value〕は楽天の'
                  '米国株口座・NISA 成長投資枠で可）。⚠ これらの ETF は規則そのもの（French の上位30%の時価加重・年1回の入れ替え）とは'
                  '銘柄数・重み・入れ替えの規則が違う近似。個別株で自分で組むなら、毎年12月末に TOPIX 大型〜中型のうち指標の上位30%を'
                  '時価加重で持ち、翌年12月末に入れ替える（数十〜百数十銘柄）'),
}

COST = 0.0025                # 片道の回転100%につき（個別株の組）
MIN_N = 50                   # JKP 日本: 三分位の銘柄数がこれ未満の月は使わない
MIN_N_REPL = 20              # JKP 他の国（小さい市場）
TURN_ACC, TURN_PRICE = 0.5, 2.0   # 事前登録の置き値（年率・片道）
PRICE_CHARS = {'ret_12_1', 'ret_6_1'}

FR_URL = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_International_Countries.zip'
FR_FILE = {'Japan': 'Japan.Dat', 'UK': 'UK.Dat', 'Austria': 'Austria.Dat', 'Australia': 'Austrlia.Dat', 'Belgium': 'Belgium.Dat',
           'Canada': 'Canada.Dat', 'Denmark': 'Denmark.Dat', 'Finland': 'Finland.Dat', 'France': 'France.Dat',
           'Germany': 'Germany.Dat', 'HongKong': 'HongKong.Dat', 'Ireland': 'Ireland.Dat', 'Italy': 'Italy.Dat',
           'Malaysia': 'Malaysia.Dat', 'Netherlands': 'Nethrlnd.Dat', 'NewZealand': 'NewZland.Dat', 'Norway': 'Norway.Dat',
           'Singapore': 'Singapor.Dat', 'Spain': 'Spain.Dat', 'Sweden': 'Sweden.Dat', 'Switzerland': 'Swtzrlnd.Dat'}
JKP_CODE = {'Japan': 'jpn', 'UK': 'gbr', 'Austria': 'aut', 'Australia': 'aus', 'Belgium': 'bel', 'Canada': 'can', 'Denmark': 'dnk',
            'Finland': 'fin', 'France': 'fra', 'Germany': 'deu', 'HongKong': 'hkg', 'Ireland': 'irl', 'Italy': 'ita',
            'Malaysia': 'mys', 'Netherlands': 'nld', 'NewZealand': 'nzl', 'Norway': 'nor', 'Singapore': 'sgp', 'Spain': 'esp',
            'Sweden': 'swe', 'Switzerland': 'che'}
REPL = [c for c in FR_FILE if c != 'Japan']          # 再現: 同じ作りの他の20か国（地域で選ばない＝結果で選ばない）
FR_COLS = ['Mkt', 'BM_H', 'BM_L', 'EP_H', 'EP_L', 'CEP_H', 'CEP_L', 'Y_H', 'Y_L', 'Y_0']
JKP_URL = 'https://jkpfactors-data.s3.amazonaws.com/public/'

VALUE6 = ['be_me', 'ni_me', 'div12m_me', 'ocf_me', 'sale_me', 'ebitda_mev']
PROF3 = ['gp_at', 'ope_be', 'qmj_prof']

# ───────────────────────── 変種（選定の前に固定・結果を見て足さない） ─────────────────────────
# 低ぶれ・低ベータ（ivol・betabab・qmj_safety）は入れない: 買いだけの低ベータの『市場との差』は、選定期間の日本（1990〜2000 の
# 下げ相場）ではベータの低さだけで大きく出る＝腕ではなく相場の向き。その系統は lowbeta_lev が受け持つ。
VARIANTS = [
    # F: French 国別（日本・1975〜）
    {'name': 'F_bm', 'src': 'F', 'legs': ['BM_H'], 'why': '簿価時価の上位30%（Fama-French 1998・Chan-Hamao-Lakonishok 1991）'},
    {'name': 'F_ep', 'src': 'F', 'legs': ['EP_H'], 'why': '益回りの上位30%'},
    {'name': 'F_cep', 'src': 'F', 'legs': ['CEP_H'], 'why': 'キャッシュ益回りの上位30%（CHL 1991 は日本で最も強いと報告）'},
    {'name': 'F_yld', 'src': 'F', 'legs': ['Y_H'], 'why': '配当利回りの上位30%'},
    {'name': 'F_val4', 'src': 'F', 'legs': ['BM_H', 'EP_H', 'CEP_H', 'Y_H'], 'why': '四つの割安の等分（一つの指標の癖を薄める）'},
    # J: JKP 日本（1986/88〜）・上限なしの時価加重
    {'name': 'J_div', 'src': 'J', 'groups': [['div12m_me']], 'w': 'vw', 'why': '配当利回りの上位1/3'},
    {'name': 'J_bm', 'src': 'J', 'groups': [['be_me']], 'w': 'vw', 'why': '簿価時価の上位1/3'},
    {'name': 'J_ep', 'src': 'J', 'groups': [['ni_me']], 'w': 'vw', 'why': '益回りの上位1/3'},
    {'name': 'J_cfp', 'src': 'J', 'groups': [['ocf_me']], 'w': 'vw', 'why': '営業CF利回りの上位1/3'},
    {'name': 'J_sp', 'src': 'J', 'groups': [['sale_me']], 'w': 'vw', 'why': '売上高÷時価の上位1/3'},
    {'name': 'J_ebev', 'src': 'J', 'groups': [['ebitda_mev']], 'w': 'vw', 'why': 'EBITDA÷企業価値の上位1/3'},
    {'name': 'J_mom', 'src': 'J', 'groups': [['ret_12_1']], 'w': 'vw', 'why': '勢い（12-1か月）の上位1/3（日本では弱いと知られる: Asness 2011）'},
    {'name': 'J_gpa', 'src': 'J', 'groups': [['gp_at']], 'w': 'vw', 'why': '粗利÷総資産の上位1/3（Novy-Marx 2013）'},
    {'name': 'J_ope', 'src': 'J', 'groups': [['ope_be']], 'w': 'vw', 'why': '営業利益÷自己資本の上位1/3（Fama-French 2015）'},
    {'name': 'J_prof', 'src': 'J', 'groups': [['qmj_prof']], 'w': 'vw', 'why': 'QMJ の収益性の上位1/3（Asness-Frazzini-Pedersen 2019）'},
    {'name': 'J_val', 'src': 'J', 'groups': [VALUE6], 'w': 'vw', 'why': '割安6指標の等分'},
    {'name': 'J_valmom', 'src': 'J', 'groups': [VALUE6, ['ret_12_1']], 'w': 'vw',
     'why': '割安＋勢い（Asness 2011「日本の勢いは割安と組むと効く」・AMP 2013）'},
    {'name': 'J_valprof', 'src': 'J', 'groups': [VALUE6, PROF3], 'w': 'vw', 'why': '割安＋収益性（Novy-Marx 2013）'},
    {'name': 'J_vmp', 'src': 'J', 'groups': [VALUE6, ['ret_12_1'], PROF3], 'w': 'vw', 'why': '割安＋勢い＋収益性'},
    {'name': 'J_div_cap', 'src': 'J', 'groups': [['div12m_me']], 'w': 'vw_cap', 'why': '配当（上限つき時価加重の組・相手は上限なし）'},
    {'name': 'J_bm_cap', 'src': 'J', 'groups': [['be_me']], 'w': 'vw_cap', 'why': '簿価時価（上限つきの組）'},
    {'name': 'J_val_cap', 'src': 'J', 'groups': [VALUE6], 'w': 'vw_cap', 'why': '割安6指標（上限つきの組）'},
    {'name': 'J_valmom_cap', 'src': 'J', 'groups': [VALUE6, ['ret_12_1']], 'w': 'vw_cap', 'why': '割安＋勢い（上限つきの組）'},
]


# ───────────────────────── 読み込み ─────────────────────────
_MEMO = {}


def fr_country(country, ccy='Dollar'):
    """French 国別 → {列: {YYYYMM: 小数}}（Value-Weight・All 4 Data Items Not Reqd・月次）。guard 済み"""
    key = ('fr', country, ccy)
    if key in _MEMO:
        return _MEMO[key]
    z = zipfile.ZipFile(io.BytesIO(h.cached('fr_F-F_International_Countries.zip', FR_URL)))
    L = z.read(FR_FILE[country]).decode('latin-1').split('\n')
    i = next(k for k, l in enumerate(L) if f'Value-Weight {ccy}' in l and 'Not Reqd' in l)
    out = {c: {} for c in FR_COLS}
    started = False
    for l in L[i + 3:]:
        p = l.split()
        if not p or not (p[0].isdigit() and len(p[0]) == 6):
            if started:
                break
            continue
        started = True
        for c, v in zip(FR_COLS, p[1:]):
            f = float(v)
            if f > -99:
                out[c][int(p[0])] = f / 100
    out = {c: h.guard(v) for c, v in out.items()}
    _MEMO[key] = out
    return out


def _jkp_counts(region, ch, w):
    """三分位の銘柄数 n（h.jkp は返さないので、同じキャッシュを h.cached で読み h.guard を通す）"""
    url = f'{JKP_URL}portfolios/%5B{region}%5D_%5B{ch}%5D_%5Bmonthly%5D_%5B{w}%5D.zip'
    z = zipfile.ZipFile(io.BytesIO(h.cached(f'jkp_portfolio_{region}_{ch}_{w}.zip', url)))
    out = {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        try:
            out.setdefault(x['pf'], {})[int(x['date'][:4]) * 100 + int(x['date'][5:7])] = int(float(x['n']))
        except (TypeError, ValueError):
            continue
    return {k: h.guard(v) for k, v in out.items()}


def jleg(region, ch, w, side='3.0'):
    """JKP の良い側の脚 → (超過リターン {m}, 銘柄数 {m})。取れなければ ({}, {})"""
    key = ('j', region, ch, w, side)
    if key not in _MEMO:
        try:
            p = h.jkp(region, ch, 'portfolio', w)
            n = _jkp_counts(region, ch, w)
            _MEMO[key] = (p.get(side, {}), n.get(side, {}))
        except Exception:
            _MEMO[key] = ({}, {})
    return _MEMO[key]


def jkp_mkt(region):
    key = ('jm', region)
    if key not in _MEMO:
        try:
            _MEMO[key] = h.jkp(region, 'mkt', 'factor', 'vw')
        except Exception:
            _MEMO[key] = {}
    return _MEMO[key]


def prefetch(regions, chars, w):
    todo = [(r, c) for r in regions for c in chars if ('j', r, c, w, '3.0') not in _MEMO]
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda rc: jleg(rc[0], rc[1], w), todo))
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(jkp_mkt, [r for r in regions if ('jm', r) not in _MEMO]))


# ───────────────────────── 組み立て ─────────────────────────
def combine(legs, turn, rf, months):
    """legs: {名前: (総リターン {m}, 使える月の集合, 群)}。群を等分し、群の中は使える脚を等分。
    月 m に使える脚は m−1 月末に分かる（French は前年12月末に組んだ組があるか・JKP は組んだ時点の銘柄数）。
    → ret {m}・tv {m}（脚の中の入れ替え＋重みの戻し）"""
    ret, tv, prev = {}, {}, None
    for m in months:
        if m not in rf:
            continue
        act = [k for k, (r, ok, g) in legs.items() if m in r and m in ok]
        if not act:
            prev = None
            continue
        grp = {}
        for k in act:
            grp.setdefault(legs[k][2], []).append(k)
        tw = {k: 1 / len(grp) / len(ks) for g, ks in grp.items() for k in ks}
        within = sum(x * turn[k] / 12 for k, x in tw.items())
        reb = 0.0 if prev is None else 0.5 * sum(abs(prev.get(k, 0.0) - tw.get(k, 0.0)) for k in set(prev) | set(tw))
        r = sum(x * legs[k][0][m] for k, x in tw.items())
        ret[m], tv[m] = r, within + reb
        g = {k: x * (1 + legs[k][0][m]) for k, x in tw.items()}
        s = sum(g.values())
        prev = {k: v / s for k, v in g.items()} if s > 0 else None
    return ret, tv


def build_F(spec, country, rf):
    d = fr_country(country, spec.get('ccy', 'Dollar'))
    bench = d['Mkt']
    legs = {c: (d[c], set(d[c]), c) for c in spec['legs'] if d.get(c)}
    if not legs or not bench:
        return {}, {}, {}
    months = sorted(set(bench) & set().union(*[set(v[0]) for v in legs.values()]))
    ret, tv = combine(legs, {c: TURN_ACC for c in legs}, rf, months)
    return ret, tv, bench


def build_J(spec, region, rf, min_n):
    w = spec['w']
    mk = jkp_mkt(region)
    bench = {m: v + rf[m] for m, v in mk.items() if m in rf}
    legs, turn = {}, {}
    for gi, g in enumerate(spec['groups']):
        for ch in g:
            r, n = jleg(region, ch, w)
            if not r:
                continue
            tot = {m: v + rf[m] for m, v in r.items() if m in rf}
            ok = {m for m, k in n.items() if k >= min_n}
            legs[ch] = (tot, ok, gi)
            turn[ch] = TURN_PRICE if ch in PRICE_CHARS else TURN_ACC
    if not legs or not bench:
        return {}, {}, {}
    months = sorted(set(bench) & set().union(*[v[1] & set(v[0]) for v in legs.values()]))
    if spec.get('start'):
        months = [m for m in months if m >= spec['start']]
    ret, tv = combine(legs, turn, rf, months)
    return ret, tv, bench


def build(spec, country, rf, repl=False):
    if spec['src'] == 'F':
        return build_F(spec, country, rf)
    return build_J(spec, JKP_CODE[country], rf, MIN_N_REPL if repl else spec.get('min_n', MIN_N))


def run(spec):
    """→ {'ret','bench','rf','turnover','cost','markets'}（すべて月次 {YYYYMM: 小数}・米ドル建ての総リターン）"""
    _, rf = h.us_market()
    if spec['src'] == 'J':
        prefetch([JKP_CODE[c] for c in ['Japan'] + list(spec.get('replicate', []))],
                 sorted({c for g in spec['groups'] for c in g}), spec['w'])
    ret, tv, bench = build(spec, 'Japan', rf)
    out = {'ret': ret, 'bench': bench, 'rf': rf, 'turnover': tv, 'cost': COST, 'markets': {}}
    for c in spec.get('replicate', []):
        r, t, b = build(spec, c, rf, repl=True)
        if r and b:
            out['markets'][c] = {'ret': r, 'bench': b, 'rf': rf, 'turnover': t, 'cost': COST}
    return out


# ───────────────────────── 選定の道具 ─────────────────────────
def spec_of(v, replicate=True):
    s = {k: v[k] for k in ('name', 'src', 'legs', 'groups', 'w') if k in v}
    if v['src'] == 'F':
        s['ccy'] = 'Dollar'
        s['bench'] = 'French International Countries の同じ国の Mkt（Value-Weight・All 4 Data Items Not Reqd・米ドル・配当込み）'
    else:
        s['bench'] = "JKP の同じ国の 'mkt'（vw＝上限なしの時価加重）＋ French RF（米ドルの総リターン）"
    s['cost_per_turnover'] = COST
    s['turnover_placed'] = '会計の信号 50%/年・価格の信号 200%/年（事前登録の置き値）＋合成の等分への戻し'
    s['replicate'] = REPL if replicate else []
    return s


def beta_alpha(ret, bench, tv, rf, a=None, b=None):
    """相手に対する β と Jensen の α（費用後・超過リターンの回帰）。選ぶのには使わない（診断だけ）"""
    ms = [m for m in sorted(set(ret) & set(bench) & set(rf)) if (a is None or m >= a) and (b is None or m <= b)]
    x = [bench[m] - rf[m] for m in ms]
    y = [ret[m] - tv.get(m, 0.0) * COST - rf[m] for m in ms]
    mx, my = S.mean(x), S.mean(y)
    cov = sum((p - mx) * (q - my) for p, q in zip(x, y)) / (len(ms) - 1)
    beta = cov / S.variance(x)
    res = [q - beta * p for p, q in zip(x, y)]
    al = S.mean(res)
    sd = S.stdev(res)
    return round(beta, 2), round(al * 1200, 2), round(al / (sd / math.sqrt(len(ms))), 2)


def evaluate_variants(verbose=True):
    _, rf = h.us_market()
    prefetch(['jpn'], sorted({c for v in VARIANTS if v['src'] == 'J' for g in v['groups'] for c in g}), 'vw')
    prefetch(['jpn'], sorted({c for v in VARIANTS if v['src'] == 'J' and v['w'] == 'vw_cap' for g in v['groups'] for c in g}), 'vw_cap')
    rows = []
    for v in VARIANTS:
        r = run(spec_of(v, replicate=False))
        st = h.stats(r['ret'], r['bench'], r['rf'], turnover=r['turnover'], cost=COST)
        if not st:
            rows.append({'name': v['name'], 'stats': None})
            continue
        be, al, alt = beta_alpha(r['ret'], r['bench'], r['turnover'], r['rf'])
        mid = 198712
        s1 = h.stats(r['ret'], r['bench'], r['rf'], b=mid, turnover=r['turnover'], cost=COST)
        s2 = h.stats(r['ret'], r['bench'], r['rf'], a=h.add_months(mid, 1), turnover=r['turnover'], cost=COST)
        tvy = S.mean(r['turnover'].values()) * 12
        rows.append({'name': v['name'], 'src': v['src'], 'stats': st, 'beta': be, 'alpha': al, 'alpha_t': alt,
                     'turn_yr': round(tvy, 2), 'first_half': s1, 'second_half': s2})
    return rows


def choose(rows):
    ok = [x for x in rows if x['stats'] and x['stats']['t'] is not None]
    elig = [x for x in ok if x['stats']['excess'] >= 1.0]
    pool = elig if elig else ok
    best = max(pool, key=lambda x: x['stats']['t'])
    return best, bool(elig)


def show(rows):
    print(f"{'変種':14} {'期間':15} {'年率':>6} {'相手':>6} {'超過':>6} {'t':>5} {'NW':>5} {'ぶれ':>5}/{'相手':<5} {'下落':>6}/{'相手':<6} "
          f"{'β':>5} {'α':>6} {'αt':>5} {'回転':>5}  前半(〜1987) / 後半")
    for x in rows:
        s = x['stats']
        if not s:
            print(f"{x['name']:14} データ不足"); continue
        f1, f2 = x['first_half'], x['second_half']
        fh = f"{f1['excess']:+.2f}(t{f1['t']})" if f1 else '—'
        sh = f"{f2['excess']:+.2f}(t{f2['t']})" if f2 else '—'
        print(f"{x['name']:14} {s['from']}-{s['to']} {s['cagr']:6.2f} {s['bench_cagr']:6.2f} {s['excess']:+6.2f} {s['t']:5.2f} {s['t_nw']:5.2f} "
              f"{s['vol']:5.1f}/{s['bench_vol']:<5} {s['maxdd']:6.1f}/{s['bench_maxdd']:<6} {x['beta']:5.2f} {x['alpha']:+6.2f} {x['alpha_t']:5.2f} "
              f"{x['turn_yr']:5.2f}  {fh} / {sh}")


# ───────────────────────── 先読みの検査 ─────────────────────────
_LA_CODE = r'''
import json, os, sys
sys.path.insert(0, %r)
import fam_japan as F
spec = json.loads(sys.argv[1])
r = F.run(spec)
print(json.dumps({'ret': r['ret'], 'bench': r['bench'], 'markets': {k: x['ret'] for k, x in r['markets'].items()}}))
'''


def _run_cut(spec, cut):
    env = dict(os.environ, EDGE_SEL_END=str(cut))            # EDGE_PHASE は触らない（select のまま・切りを前へずらすだけ）
    p = subprocess.run([sys.executable, '-c', _LA_CODE % os.path.dirname(os.path.abspath(__file__)), json.dumps(spec)],
                       capture_output=True, text=True, env=env, timeout=3600)
    if p.returncode:
        raise RuntimeError(p.stderr[-800:])
    return json.loads(p.stdout.strip().split('\n')[-1])


def lookahead(spec):
    """(1) 接頭辞の検査: データを 1990-12・1995-12 で切った成績が 2000-12 まで読んだ成績と、切った月まで1ビットも違わない
       （規則が後のデータを使っていれば違う）。他の市場も同じ。
    (2) 日付の揃い: 組の月次リターンと相手（同じ月）の相関が高く、1か月ずらすと消える（組のリターンが翌月へずれていない）。
    (3) 合成の重みの検査: 合成の重みを決める『使える脚』を 1か月前の銘柄数で決め直しても（より保守的）成績がほぼ同じ"""
    full = _run_cut(spec, 200012)
    res = {}
    for cut in (199012, 199512):
        part = _run_cut(spec, cut)
        bad, n = [], 0
        for key in ['ret', 'bench']:
            for m, v in part[key].items():
                if int(m) > cut:
                    continue
                n += 1
                w = full[key].get(m)
                if w is None or abs(v - w) > 1e-12:
                    bad.append((key, m))
        for c, ser in part['markets'].items():
            for m, v in ser.items():
                if int(m) > cut:
                    continue
                n += 1
                w = full['markets'].get(c, {}).get(m)
                if w is None or abs(v - w) > 1e-12:
                    bad.append((c, m))
        res[f'prefix_{cut}'] = {'checked': n, 'mismatch': len(bad), 'examples': bad[:5]}
    r, b = full['ret'], full['bench']
    ms = sorted(set(r) & set(b))
    x0 = [r[m] for m in ms]
    y0 = [b[m] for m in ms]
    lag = [(r[ms[i]], b[ms[i - 1]]) for i in range(1, len(ms))]
    lead = [(r[ms[i - 1]], b[ms[i]]) for i in range(1, len(ms))]
    res['corr_same_month'] = round(S.correlation(x0, y0), 3)
    res['corr_ret_vs_prev_bench'] = round(S.correlation([p for p, q in lag], [q for p, q in lag]), 3)
    res['corr_ret_vs_next_bench'] = round(S.correlation([p for p, q in lead], [q for p, q in lead]), 3)
    return res


def reference(spec):
    """選ぶのには使わない参考（どれも 2000-12 まで）: (a) 同じ規則を米国（French の米国の Hi 30・1951-07〜）に当てた成績
    (b) 同じ凍結した規則の他の20か国での選定期間の成績とならし"""
    mk, rf = h.us_market()
    legs = {}
    for nm, f in [('BM_H', 'Portfolios_Formed_on_BE-ME'), ('EP_H', 'Portfolios_Formed_on_E-P'),
                  ('CEP_H', 'Portfolios_Formed_on_CF-P'), ('Y_H', 'Portfolios_Formed_on_D-P')]:
        if nm not in spec.get('legs', []):
            continue
        d = h.french(f)
        t = next(k for k in d if 'Value Weight' in k and 'Monthly' in k)
        ser = {m: v / 100 for m, v in d[t]['Hi 30'].items() if m > 9999}
        legs[nm] = (ser, set(ser), nm)
    out = {}
    if legs:
        ms = [m for m in sorted(set(mk) & set().union(*[set(v[0]) for v in legs.values()])) if m >= 195107]
        r, tv = combine(legs, {k: TURN_ACC for k in legs}, rf, ms)
        out['us_same_rule_1951_2000'] = h.stats(r, mk, rf, turnover=tv, cost=COST)
    x = run(spec)
    per, rows, pos = {}, {}, 0
    for c, y in x['markets'].items():
        st = h.stats(y['ret'], y['bench'], y['rf'], turnover=y['turnover'], cost=COST)
        if st:
            rows[c] = {'from': st['from'], 'excess': st['excess'], 't': st['t']}
            pos += st['excess'] > 0
        for m in y['ret']:
            if m in y['bench']:
                per.setdefault(m, []).append(y['ret'][m] - y['turnover'].get(m, 0.0) * COST - y['bench'][m])
    ex = [S.mean(v) for m, v in sorted(per.items())]
    mu, sd = S.mean(ex), S.stdev(ex)
    out['other20_selection_period'] = {'positive': f'{pos}/{len(rows)}', 'pooled_excess': round(mu * 1200, 2),
                                       'pooled_t': round(mu / (sd / math.sqrt(len(ex))), 2), 'by_country': rows}
    return out


def freeze():
    rows, best, elig = main()
    v = next(x for x in VARIANTS if x['name'] == best['name'])
    spec = spec_of(v)
    la = lookahead(spec)
    assert all(la[k]['mismatch'] == 0 for k in la if k.startswith('prefix_')), la
    ref = reference(spec)
    st, b = best['stats'], best
    loc = spec_of(v, False); loc['ccy'] = 'Local'
    _, rf = h.us_market()
    rl, tl, bl = build_F(loc, 'Japan', rf) if v['src'] == 'F' else ({}, {}, {})
    yen = h.stats(rl, bl, rf, turnover=tl, cost=COST) if rl else None
    us, o20 = ref.get('us_same_rule_1951_2000') or {}, ref['other20_selection_period']
    rationale = (
        f"規則: 日本株（French 国別＝MSCI 由来の大型〜中型）を毎年12月末に 簿価時価・益回り・キャッシュ益回り・配当利回り の四つで並べ、"
        f"それぞれの上位30%（時価加重）を等分に持つ（月ごとに等分へ戻す）。相手は同じファイルの日本の市場（時価加重）。\n"
        f"なぜ: 日本の割安の上乗せは Chan・Hamao・Lakonishok（1991・1971-88 の東証で B/M と CF/P が強い）、Fama-French（1998・国際の割安）、"
        f"Asness・Moskowitz・Pedersen（2013）が報告している。経済的な理由は (1) 割安な株は将来の利益の伸びを悲観しすぎた価格で買える（行動の説明）"
        f"(2) 苦境のリスクへの報酬（リスクの説明）。一つの比率には会計の癖（日本は持ち合い株で簿価が歪む・配当性向が低く配当利回りの"
        f"ばらつきが小さい）があるので、四つを等分にして癖を薄める——このため t が単独の指標より高く出た。\n"
        f"選定期間（{st['from']}〜{st['to']}・{st['years']}年）の結果: 費用後 年率 {st['cagr']}% vs 市場 {st['bench_cagr']}%＝超過 {st['excess']:+}%/年"
        f"（t {st['t']}・NW {st['t_nw']}）、ぶれ {st['vol']}/{st['bench_vol']}%、最大下落 {st['maxdd']}/{st['bench_maxdd']}%、"
        f"β {b['beta']}・α {b['alpha']:+}%/年（t {b['alpha_t']}）＝下げ相場でβが低かっただけではない。転がる10年 {st['roll10_win']}。"
        f"前半（〜1987）{b['first_half']['excess']:+}%（t {b['first_half']['t']}）／後半（1988〜2000）{b['second_half']['excess']:+}%（t {b['second_half']['t']}）"
        f"＝前半は弱い。円建てでも超過 {yen['excess']:+}%（t {yen['t']}）。\n"
        f"選び方: 事前登録どおり、試した {len(rows)} 変種のうち選定期間の超過が +1%/年以上で費用後の超過の t が最大のもの"
        f"（次点は F_cep t2.37・F_bm t2.21。JKP 日本の変種は被覆が 1987/88〜 と短く t はどれも 2.2 未満）。\n"
        f"選ぶのに使っていない参考（どれも 2000-12 まで）: 同じ規則を米国に当てると 1951-2000 で 超過 {us.get('excess')!s}%/年（t {us.get('t')!s}）。"
        f"同じ規則を他の20か国に当てると選定期間で {o20['positive']} が正・ならして {o20['pooled_excess']:+}%/年（t {o20['pooled_t']}）。")
    table = [{'name': x['name'], 'excess': x['stats']['excess'], 't': x['stats']['t'], 't_nw': x['stats']['t_nw'],
              'from': x['stats']['from'], 'beta': x['beta'], 'alpha': x['alpha']} for x in rows if x['stats']]
    extra = {
        'implement': FAMILY['implement'],
        'lookahead_test': ('(1) 接頭辞の検査: データを 1990-12・1995-12 で切って run(spec) を回した日本と他の20か国の月次の成績が、2000-12 まで'
                           f"読んだ成績と切った月まで一致（{la['prefix_199012']['checked']}・{la['prefix_199512']['checked']} 点・不一致0）。"
                           f"(2) 日付の揃い: 組と相手の同じ月の相関 {la['corr_same_month']}・組と前月の相手 {la['corr_ret_vs_prev_bench']}・"
                           f"組と翌月の相手 {la['corr_ret_vs_next_bench']}＝組のリターンは月がずれていない。"
                           '(3) コードを読む検査: 月 m の持ち高は French が前年12月末に組んだ上位30%（データの作り手の組入れ）で、合成の重みは'
                           'その月に組が存在するかだけで決まる（その月のリターンを使わない）。月ごとの等分への戻しの回転は m−1 月末までの値動きで決まる。'
                           '⚠ French の国別の組は12月末に比率で並べる。比率の会計年度の時点はページに書かれていない——日本は3月決算が多く6月までに'
                           '公表されるので12月の組入れには先読みにならないが、12月決算の国（再現の側）では数か月の先読みがありうる（データの作り手の側の問題）'),
        'variants_table': table,
        'markets': REPL,
        'asia_pacific_subset': ['HongKong', 'Singapore', 'Malaysia', 'Australia', 'NewZealand'],
        'reference_selection_period': ref,
        'selection_diag': {'beta': b['beta'], 'alpha': b['alpha'], 'alpha_t': b['alpha_t'], 'first_half': b['first_half'],
                           'second_half': b['second_half'], 'yen': yen},
        'excluded_before_selection': '低ぶれ・低ベータ（ivol・betabab・qmj_safety）＝下げ相場の選定期間でβの低さだけで勝って見えるため／'
                                     'eqnpo_me・fcf_me＝JKP 日本で 2000-08 まで被覆が無く選定期間で測れないため',
        'chose_by_rule': elig,
    }
    doc = h.save_spec('japan', spec, rationale, len(rows), st, extra=extra)
    print('凍結:', json.dumps(doc['spec'], ensure_ascii=False))
    return doc


def main():
    rows = evaluate_variants()
    show(rows)
    best, elig = choose(rows)
    print(f"\n選ぶ規則: {best['name']}（{'超過 +1%/年以上の中で t 最大' if elig else '⚠ +1%/年に届く変種なし→t 最大を選んだ'}）  変種の数 {len(rows)}")
    return rows, best, elig


if __name__ == '__main__':
    if '--freeze' in sys.argv:
        freeze()
    elif '--lookahead' in sys.argv:
        nm = sys.argv[sys.argv.index('--lookahead') + 1] if len(sys.argv) > sys.argv.index('--lookahead') + 1 else None
        v = next(x for x in VARIANTS if x['name'] == nm)
        print(json.dumps(lookahead(spec_of(v)), ensure_ascii=False, indent=1))
    else:
        rows, best, elig = main()
        json.dump(rows, open(os.path.join(os.environ.get('JP_SCRATCH', '/tmp'), 'japan_rows.json'), 'w'), ensure_ascii=False, indent=1) \
            if os.environ.get('JP_SCRATCH') else None
