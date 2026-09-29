#!/usr/bin/env python3
"""night/mw_japan_verify.py — 角度 japan（日本株・買いだけ）の『反証の検証』（読むだけ・門の判定には不使用）

対象: night/mw_japan.py → out/mw_japan.json が S/A と主張した候補（＋B の上位2本）。
この道具は mw_common の**取得部品だけ**（get / jkp_rows / french_tables / ff_factors）を使い、
ポートフォリオの組み立て・超過・NW t・CAGR・転がる窓・積立・Holm・格付けの線は**すべて自前**で書き直した。

調べること
 1. 数字の再現（全期間・訓練・保有の超過と NW t・CAGR の差・転がる20年・積立20年・費用後の保有期間）
 2. 後知恵: 良い側の決め方、保有期間を見てから決めた変数、角度そのものを選んだ時点で保有期間の結果が既知だったか
 3. 相手（純粋な時価加重か）、超過と総リターンの混同、通貨（米ドル↔円）
 4. 区間の依存（1998-2000 を抜く・2020-2021 を抜く・保有期間の前半/後半・2023 の東証 PBR 要請の前まで）
 5. 変数の脆さ（隣の定義: vw_cap・Reqd 表・米ドル表・大型株だけ・25分割の再合成・選択の閾値や n の下限）
 6. 多重検定（角度の全 280 本での Holm・全期間 t の Bonferroni 線・同じ賭けの重複）
 7. 実行の現実（費用の損益分岐・回転の2倍×0.30%・課税口座での売却益課税の繰り延べの損）
 8. 保有期間だけでの他国の再現（C5 は全期間で測られている＝保有期間の独立の答え合わせにならない）
出力: out/mw_japan_verify.json
"""
import csv, io, json, math, os, re, sys, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402  （取得部品だけを使う）

OUT = os.path.join(M.BASE, 'out', 'mw_japan_verify.json')
TRAIN_END, HOLD = 200612, 200701
JKP0 = 198701
TAX = 0.20315
COST = 0.001
REPL_JKP = ['aus', 'hkg', 'sgp', 'nzl', 'gbr', 'deu', 'fra', 'che', 'nld', 'swe', 'ita', 'esp', 'dnk', 'nor', 'bel', 'fin', 'aut', 'irl', 'prt']
FR_FILES = {'Japan': 'Japan.Dat', 'UK': 'UK.Dat', 'Austria': 'Austria.Dat', 'Australia': 'Austrlia.Dat', 'Belgium': 'Belgium.Dat',
            'Canada': 'Canada.Dat', 'Denmark': 'Denmark.Dat', 'Finland': 'Finland.Dat', 'France': 'France.Dat', 'Germany': 'Germany.Dat',
            'HongKong': 'HongKong.Dat', 'Ireland': 'Ireland.Dat', 'Italy': 'Italy.Dat', 'Malaysia': 'Malaysia.Dat',
            'Netherlands': 'Nethrlnd.Dat', 'NewZealand': 'NewZland.Dat', 'Norway': 'Norway.Dat', 'Singapore': 'Singapor.Dat',
            'Spain': 'Spain.Dat', 'Sweden': 'Sweden.Dat', 'Switzerland': 'Swtzrlnd.Dat'}


# ═════════════════════════ 自前の統計 ═════════════════════════
def nwt(x, L=12):
    n = len(x)
    if n < 24:
        return None
    m = math.fsum(x) / n
    e = [v - m for v in x]
    s = math.fsum(v * v for v in e) / n
    for l in range(1, L + 1):
        s += 2 * (1 - l / (L + 1)) * math.fsum(e[i] * e[i - l] for i in range(l, n)) / n
    return m / math.sqrt(s / n) if s > 0 else None


def p2(t):
    return None if t is None else math.erfc(abs(t) / math.sqrt(2))


def geo(xs):
    return math.exp(math.fsum(math.log1p(v) for v in xs) * 12 / len(xs)) - 1


def months(s, b, a=None, z=None, drop=None):
    return [k for k in sorted(set(s) & set(b)) if (a is None or k >= a) and (z is None or k <= z)
            and not (drop and any(d0 <= k <= d1 for d0, d1 in drop))]


def ex(s, b, a=None, z=None, drop=None, raw_t=False):
    ks = months(s, b, a, z, drop)
    if len(ks) < 24:
        return None
    d = [s[k] - b[k] for k in ks]
    t = nwt(d)
    sd = math.sqrt(math.fsum((v - math.fsum(d) / len(d)) ** 2 for v in d) / (len(d) - 1))
    gs, gb = geo([s[k] for k in ks]), geo([b[k] for k in ks])
    o = {'from': ks[0], 'to': ks[-1], 'years': round(len(ks) / 12, 2), 'ex': round(math.fsum(d) / len(d) * 1200, 2),
         't': round(t, 2) if t is not None else None, 'p': round(p2(t), 5) if t is not None else None,
         'cagr_s': round(gs * 100, 2), 'cagr_b': round(gb * 100, 2), 'cagr_diff': round((gs - gb) * 100, 2),
         'te': round(sd * math.sqrt(12) * 100, 2)}
    if raw_t:
        o['t_raw'] = t
    return o


def roll(s, b, years, a=None, z=None, start_month=7):
    """毎年 start_month 起点・一括。窓の月が 97% 以上そろう窓だけ"""
    ks = months(s, b, a, z)
    if not ks:
        return None
    ss = set(ks)
    out = []
    for y in range(ks[0] // 100, ks[-1] // 100 + 1):
        w = []
        yy, mm = y, start_month
        for _ in range(years * 12):
            w.append(yy * 100 + mm)
            mm += 1
            if mm == 13:
                yy, mm = yy + 1, 1
        if w[-1] > ks[-1] or w[0] < ks[0]:
            continue
        have = [k for k in w if k in ss]
        if len(have) < 0.97 * len(w):
            continue
        gs = math.exp(math.fsum(math.log1p(s[k]) for k in have) / years) - 1
        gb = math.exp(math.fsum(math.log1p(b[k]) for k in have) / years) - 1
        out.append((y, round((gs - gb) * 100, 2)))
    if not out:
        return None
    v = sorted(c for _, c in out)
    return {'windows': len(out), 'wins': sum(1 for c in v if c > 0), 'win_rate': round(sum(1 for c in v if c > 0) / len(v), 3),
            'median': v[len(v) // 2], 'worst': min(out, key=lambda x: x[1]), 'best': max(out, key=lambda x: x[1])}


def dca(s, b, years=20, step=12, a=None, z=None):
    ks = months(s, b, a, z)
    n = years * 12
    out = []
    for i in range(0, len(ks) - n + 1, step):
        ws = wb = 0.0
        for k in ks[i:i + n]:
            ws = (ws + 1) * (1 + s[k])
            wb = (wb + 1) * (1 + b[k])
        out.append((ks[i], round(ws / wb, 3)))
    if not out:
        return None
    v = sorted(r for _, r in out)
    return {'windows': len(out), 'win_rate': round(sum(1 for r in v if r > 1) / len(v), 3), 'median': v[len(v) // 2],
            'worst': min(out, key=lambda x: x[1])}


def holm(ps):
    it = sorted((p, k) for k, p in ps.items() if p is not None)
    m, run, out = len(it), 0.0, {}
    for i, (p, k) in enumerate(it):
        run = max(run, min(1.0, (m - i) * p))
        out[k] = round(run, 5)
    return out


def cost(s, turnover, unit):
    c = turnover * unit / 12
    return {k: v - c for k, v in s.items()}


def my_grade(full, train, hold, r20, costh, repl_pos=None, repl_n=None, holm_p=None, full_t_ok=None):
    """out/mw_prereg.json の C1〜C7 を自前で（訓練期間は最低15年）"""
    c = {}
    c['C1'] = bool(train and train['years'] >= 15 and train['ex'] > 0 and (train['t'] or 0) >= 2.0)
    c['C2'] = bool(hold and hold['ex'] > 0 and hold['cagr_diff'] > 0)
    c['C3'] = bool(hold and (hold['t'] or 0) >= 1.65)
    c['C4'] = bool(r20 and r20['win_rate'] >= 0.8)
    c['C5'] = None if not repl_n else (repl_pos / repl_n >= 2 / 3)
    c['C6'] = bool(costh and costh['ex'] > 0 and costh['cagr_diff'] > 0)
    ft = full_t_ok if full_t_ok is not None else bool(full and (full['t'] or 0) >= 3.0)
    c['C7'] = bool(ft or (holm_p is not None and holm_p < 0.05))
    base = c['C1'] and c['C2'] and c['C6']
    if base and c['C3'] and c['C4'] and c['C7'] and c['C5'] is not False:
        g = 'S'
    elif base and c['C4'] and c['C7'] and (c['C3'] or c['C5'] is True):
        g = 'A'
    elif base:
        g = 'B'
    else:
        g = 'C'
    return g, c


# ═════════════════════════ データ（取得は mw_common、読み解きは自前） ═════════════════════════
RF = M.ff_factors()['rf']          # French の RF（米国短期国債・小数）
AVAIL = json.loads(M.get('https://jkpfactors-data.s3.amazonaws.com/public/availability.json', name='jkp_availability.json'))['portfolios']


def ym(d):
    return int(d[:4]) * 100 + int(d[5:7])


def read_dirs():
    rows = M.jkp_rows('usa', 'all_factors', 'factor', 'vw_cap')
    return {x['name']: int(x['direction']) for x in rows}


DIRS = read_dirs()
_P, _MK = {}, {}


def jpf(region, key, w='vw'):
    """{pf: {ym: (ret超過, n)}} or None"""
    k = (region, key, w)
    if k not in _P:
        if key not in AVAIL.get(region, []):
            _P[k] = None
        else:
            d = {}
            for x in M.jkp_rows(region, key, 'portfolios', w):
                if x['ret'] in ('', 'NA', 'na'):
                    continue
                n = int(float(x['n'])) if x['n'] not in ('', 'NA') else 0
                d.setdefault(x['pf'], {})[ym(x['date'])] = (float(x['ret']), n)
            _P[k] = d
    return _P[k]


def jmkt(region, w='vw'):
    k = (region, w)
    if k not in _MK:
        _MK[k] = {ym(x['date']): float(x['ret']) for x in M.jkp_rows(region, 'mkt', 'factor', w) if x['ret'] not in ('', 'NA', 'na')}
    return _MK[k]


def side_of(key):
    return '3.0' if DIRS[key] == 1 else '1.0'


def jcomp(region, comps, w='vw', nmin=0, need='all', start=JKP0):
    """comps=[(key, side)]。月ごとに n≥nmin の構成要素の等分平均（超過）。need='all' 全部そろう月 / 'half' 半分以上 / 数値=その割合以上"""
    ser = []
    for k, sd in comps:
        p = jpf(region, k, w)
        ser.append({} if p is None or sd not in p else {m: r for m, (r, n) in p[sd].items() if n >= nmin})
    allm = sorted(set().union(*[set(x) for x in ser])) if ser else []
    out = {}
    for m in allm:
        if start is not None and m < start:
            continue
        v = [x[m] for x in ser if m in x]
        if not v:
            continue
        frac = len(v) / len(ser)
        if (need == 'all' and len(v) == len(ser)) or (need == 'half' and frac >= 0.5) or (isinstance(need, float) and frac >= need):
            out[m] = math.fsum(v) / len(v)
    return out


def addrf(x):
    return {k: v + RF[k] for k, v in x.items() if k in RF}


FR_ZIP = None


def fr_block(country, cur='Local', req='Not Reqd', col=None, wout=False):
    """French International Countries の月次・時価加重の表を自前で読む → {列: {ym: 小数}}"""
    name = 'fr_F-F_International_Countries_Wout_Div.zip' if wout else 'fr_F-F_International_Countries.zip'
    url = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/' + name[3:]
    z = zipfile.ZipFile(io.BytesIO(M.get(url, name=name)))
    cols = ['Mkt', 'BM_H', 'BM_L', 'EP_H', 'EP_L', 'CEP_H', 'CEP_L', 'YLD_H', 'YLD_L', 'YLD_0']
    out = {c: {} for c in cols}
    on = False
    for line in z.read(FR_FILES[country]).decode('latin-1').splitlines():
        if 'Value-Weight' in line or 'Average of Annual' in line:
            on = ('Value-Weight' in line) and (cur in line) and (req in line)
            continue
        m = re.match(r'^\s*(\d{6})\s+(.*)$', line)
        if on and m:
            vals = m.group(2).split()
            for c, x in zip(cols, vals):
                v = float(x)
                if v <= -99.99 or v == -999:
                    continue
                out[c][int(m.group(1))] = v / 100
    return out


def fr_mix(d, cols):
    ms = set(d[cols[0]])
    for c in cols[1:]:
        ms &= set(d[c])
    return {m: math.fsum(d[c][m] for c in cols) / len(cols) for m in sorted(ms)}


def fr_tab(name, want):
    for t, v in M.french_tables(name).items():
        if want.lower() in t.lower() and v['freq'] == 'monthly':
            o = {c: {} for c in v['cols']}
            for d, row in v['data'].items():
                for c, x in zip(v['cols'], row):
                    if x is not None:
                        o[c][d] = x
            return o
    raise KeyError((name, want))


def fr_region_mkt(region):
    t = fr_tab(f'{region}_3_Factors', 'missing')  # 表題が『Missing data…』
    return {d: (t['Mkt-RF'][d] + t['RF'][d]) / 100 for d in t['Mkt-RF'] if d in t['RF']}


def fr25_vw(region, cells, fname='25_Portfolios_ME_BE-ME'):
    """25分割のセルを時価（社数×平均の時価）で重み付けして合成（月初の重み）。{ym: 小数}"""
    r = fr_tab(f'{region}_{fname}', 'Value Weighted Returns -- Monthly')
    n = fr_tab(f'{region}_{fname}', 'Number of Firms')
    sz = fr_tab(f'{region}_{fname}', 'Average Firm Size')
    out = {}
    for m in sorted(r[cells[0]]):
        num = den = 0.0
        ok = True
        for c in cells:
            if m not in r[c] or m not in n[c] or m not in sz[c]:
                ok = False
                break
            w = n[c][m] * sz[c][m]
            num += w * r[c][m] / 100
            den += w
        if ok and den > 0:
            out[m] = num / den
    return out


def fr25_weight_share(region, cells, fname='25_Portfolios_ME_BE-ME', at=None):
    n = fr_tab(f'{region}_{fname}', 'Number of Firms')
    sz = fr_tab(f'{region}_{fname}', 'Average Firm Size')
    allc = list(n)
    res = {}
    for m in at:
        tot = sum(n[c][m] * sz[c][m] for c in allc if m in n[c] and m in sz[c])
        sub = sum(n[c][m] * sz[c][m] for c in cells if m in n[c] and m in sz[c])
        res[m] = {'share_of_mkt_cap': round(sub / tot, 3) if tot else None, 'firms': sum(n[c][m] for c in cells if m in n[c])}
    return res


# 円⇔米ドル: French Intl 日本の Mkt（現地と米ドル）から月々の為替の変化を出す（S_t/S_{t-1}＝1ドルあたりの円の比）
_FL, _FD = fr_block('Japan', 'Local'), fr_block('Japan', 'Dollar')
FXF = {m: (1 + _FL['Mkt'][m]) / (1 + _FD['Mkt'][m]) for m in set(_FL['Mkt']) & set(_FD['Mkt'])}


def to_jpy(usd_tot):
    return {m: (1 + v) * FXF[m] - 1 for m, v in usd_tot.items() if m in FXF}


# ═════════════════════════ 回転（研究側の事前登録の分類を自前で書き直し） ═════════════════════════
TURN_P = {'div12m_me': 0.6, 'be_me': 0.6, 'ni_me': 0.6, 'ocf_me': 0.6, 'eqnpo_me': 0.6, 'eqnpo_12m': 0.8, 'chcsho_12m': 1.0,
          'ope_be': 0.5, 'gp_at': 0.5, 'qmj': 0.6, 'ret_12_1': 2.0, 'ivol_capm_252d': 0.8, 'at_gr1': 1.0,
          'mispricing_mgmt': 1.0, 'mispricing_perf': 1.0, 'betabab_1260d': 0.8}


def census_turn(k):
    if (k.startswith(('ret_1_0', 'ret_3_1', 'rmax', 'rskew_21d', 'iskew_', 'rvol_21d', 'beta_dimson_21d', 'coskew_21d',
                      'bidaskhl_21d', 'zero_trades_21d', 'seas_1_1')) or (k.startswith('ivol_') and k.endswith('_21d'))):
        return 6.0
    if k in ('ret_6_1', 'ret_9_1', 'ret_12_1', 'ret_12_7', 'prc_highprc_252d') or k.startswith(('resff3_', 'seas_')):
        return 2.5
    if k.startswith(('niq_', 'saleq_', 'ocfq_')) or k == 'ni_inc8q':
        return 1.5
    return 0.8


# ═════════════════════════ 課税口座の模擬（円・売却益課税 20.315%・損は無期限で繰り越す＝戦略に甘い側） ═════════════════════════
def taxed_terminal(r, turnover, a, z):
    ks = [k for k in sorted(r) if a <= k <= z]
    V, B, loss = 1.0, 1.0, 0.0
    f = turnover / 12
    for k in ks:
        V *= 1 + r[k]
        if f > 0:
            g = f * (V - B)
            sold = f * V
            if g > 0:
                use = min(loss, g)
                loss -= use
                T = TAX * (g - use)
            else:
                loss += -g
                T = 0.0
            B = B * (1 - f) + (sold - T)
            V -= T
    g = V - B
    if g > 0:
        V -= TAX * max(0.0, g - loss)
    return V, len(ks) / 12


def tax_check(s_jpy, b_jpy, turnover, a=HOLD, z=None):
    z = z or max(set(s_jpy) & set(b_jpy))
    ks = months(s_jpy, b_jpy, a, z)
    s = {k: s_jpy[k] for k in ks}
    b = {k: b_jpy[k] for k in ks}
    Vs, yrs = taxed_terminal(s, turnover, ks[0], ks[-1])
    Vb, _ = taxed_terminal(b, 0.0, ks[0], ks[-1])
    pre_s, pre_b = geo(list(s.values())), geo(list(b.values()))
    return {'from': ks[0], 'to': ks[-1], 'turnover': turnover,
            'pre_tax_cagr_diff': round((pre_s - pre_b) * 100, 2),
            'after_tax_cagr_diff': round((Vs ** (1 / yrs) - Vb ** (1 / yrs)) * 100, 2),
            'note': '配当は総リターンに含めたまま（配当課税は両方に掛かるので差には入れていない）。売却益課税は回転ぶん毎月・相手の ETF は最後に一度だけ'}


# ═════════════════════════ 候補の組み立て ═════════════════════════
def cand_jkp(comps, w='vw', nmin=0, need='all'):
    return addrf(jcomp('jpn', comps, w, nmin, need))


def us_select(thr=2.0, nmin=30, a=196307, z=TRAIN_END, min_years=15):
    keys = sorted(k for k in AVAIL['usa'] if k != 'all_factors' and k in DIRS)
    bm = jmkt('usa', 'vw')
    sel, log = [], {}
    for k in keys:
        p = jpf('usa', k)
        if p is None:
            continue
        best = None
        for sd in ('1.0', '3.0'):
            if sd not in p:
                continue
            s = {m: r for m, (r, n) in p[sd].items() if n >= nmin and a <= m <= z}
            st = ex(s, bm, a, z)  # 超過どうし（RF は打ち消す）
            if st and st['years'] >= min_years and (best is None or st['ex'] > best[1]['ex']):
                best = (sd, st)
        if best:
            log[k] = (best[0], best[1]['ex'], best[1]['t'])
            if (best[1]['t'] or 0) >= thr:
                sel.append((k, best[0]))
    return sel, log


def clusters():
    b = M.get('https://raw.githubusercontent.com/bkelly-lab/ReplicationCrisis/master/GlobalFactors/Cluster%20Labels.csv', name='jkp_cluster_labels.csv')
    c = {}
    for x in csv.DictReader(io.StringIO(b.decode())):
        c.setdefault(x['cluster'], []).append(x['characteristic'])
    return c


JP_KEYS = sorted(k for k in AVAIL['jpn'] if k != 'all_factors' and k in DIRS)


# ═════════════════════════ 1本ぶんの全点検 ═════════════════════════
def check(name, s_tot_usd_or_jpy, b, turnover, currency, claimed, comps=None, w='vw', nmin=0, need='all', jkp=True,
          repl=None, extra=None):
    """s, b: 同じ通貨の総リターン。claimed: 研究側の主張（比較用）"""
    s = s_tot_usd_or_jpy
    R = {'name': name, 'currency': currency, 'turnover_used': turnover, 'claimed': claimed}
    full, train, hold = ex(s, b, raw_t=True), ex(s, b, z=TRAIN_END), ex(s, b, a=HOLD)
    R['full'], R['train'], R['hold'], R['recent'] = full, train, hold, ex(s, b, a=201307)
    R['full_t_unrounded'] = round(full['t_raw'], 7) if full else None
    net = cost(s, turnover, COST)
    R['cost_hold_010'] = ex(net, b, a=HOLD)
    R['cost_hold_2x_030'] = ex(cost(s, 2 * turnover, 0.003), b, a=HOLD)
    if hold and turnover:
        R['breakeven_cost_per_100pct_oneway_pct'] = round(hold['ex'] / (turnover * 100) * 100, 2)
    R['roll20'] = roll(s, b, 20)
    R['dca20'] = dca(s, b, 20)
    R['roll10_in_hold'] = roll(s, b, 10, a=HOLD)
    R['roll5_in_hold'] = roll(s, b, 5, a=HOLD)
    ks = months(s, b, HOLD)
    half = ks[len(ks) // 2] if ks else None
    R['sub'] = {
        'hold_1st_half': ex(s, b, a=HOLD, z=ks[len(ks) // 2 - 1]) if ks else None,
        'hold_2nd_half': ex(s, b, a=half) if ks else None,
        '2007-12': ex(s, b, 200701, 201212), '2013-19': ex(s, b, 201301, 201912), '2020-': ex(s, b, 202001),
        'hold_excl_2020_21': ex(s, b, a=HOLD, drop=[(202001, 202112)]),
        'hold_to_2022_before_TSE_PBR_request': ex(s, b, HOLD, 202212),
        'hold_2007_2021': ex(s, b, HOLD, 202112),
        'hold_excl_2022_25': ex(s, b, a=HOLD, drop=[(202201, 202612)]),
        'full_excl_1998_2000': ex(s, b, drop=[(199801, 200012)]),
        'train_excl_1998_2000': ex(s, b, z=TRAIN_END, drop=[(199801, 200012)]),
        'full_excl_1998_2000_and_2020_21': ex(s, b, drop=[(199801, 200012), (202001, 202112)]),
    }
    R['maxdd'] = None
    if comps and jkp:
        R['train_n30'] = ex(addrf(jcomp('jpn', comps, w, 30, need)), b, z=TRAIN_END)
        R['train_n100'] = ex(addrf(jcomp('jpn', comps, w, 100, need)), b, z=TRAIN_END)
    if extra:
        R.update(extra)
    return R


def repl_hold_jkp(comps, w='vw', nmin=0, need='all', min_years=10):
    """他の19か国で、全期間と保有期間（2007〜）それぞれの超過の符号"""
    det = {}
    for c in REPL_JKP:
        if any(k not in AVAIL.get(c, []) for k, _ in comps) and need == 'all':
            continue
        use = [(k, sd) for k, sd in comps if k in AVAIL.get(c, [])]
        if not use:
            continue
        s = jcomp(c, use, w, nmin, need if need != 'all' else 'all', start=None)
        if need != 'all' and len(use) * 2 < len(comps):
            continue
        b = jmkt(c, 'vw')
        f, h, h21 = ex(s, b), ex(s, b, a=HOLD), ex(s, b, HOLD, 202112)
        if f and f['years'] >= min_years:
            det[c] = {'full_ex': f['ex'], 'full_t': f['t'], 'hold_ex': h['ex'] if h else None, 'hold_t': h['t'] if h else None,
                      'hold_0721_ex': h21['ex'] if h21 else None, 'years': f['years']}
    n = len(det)
    return {'n': n, 'full_pos': sum(1 for v in det.values() if v['full_ex'] > 0),
            'hold_pos': sum(1 for v in det.values() if (v['hold_ex'] or 0) > 0),
            'hold_pos_t165': sum(1 for v in det.values() if (v['hold_t'] or 0) >= 1.65),
            'hold_median_ex': sorted(v['hold_ex'] for v in det.values() if v['hold_ex'] is not None)[n // 2] if n else None,
            'hold_2007_2021_pos': sum(1 for v in det.values() if (v['hold_0721_ex'] or 0) > 0),
            'detail': det}


def repl_hold_fr(cols):
    det = {}
    for c in FR_FILES:
        if c == 'Japan':
            continue
        d = fr_block(c, 'Local')
        if any(len(d[x]) < 36 for x in cols) or len(d['Mkt']) < 36:
            continue
        s = fr_mix(d, cols)
        f, h, h21 = ex(s, d['Mkt']), ex(s, d['Mkt'], a=HOLD), ex(s, d['Mkt'], HOLD, 202112)
        if f:
            det[c] = {'full_ex': f['ex'], 'hold_ex': h['ex'] if h else None, 'hold_t': h['t'] if h else None,
                      'hold_0721_ex': h21['ex'] if h21 else None}
    n = len(det)
    return {'n': n, 'full_pos': sum(1 for v in det.values() if v['full_ex'] > 0),
            'hold_pos': sum(1 for v in det.values() if (v['hold_ex'] or 0) > 0),
            'hold_pos_t165': sum(1 for v in det.values() if (v['hold_t'] or 0) >= 1.65),
            'hold_median_ex': sorted(v['hold_ex'] for v in det.values() if v['hold_ex'] is not None)[n // 2] if n else None,
            'hold_2007_2021_pos': sum(1 for v in det.values() if (v['hold_0721_ex'] or 0) > 0),
            'detail': det}


def excess_series(s, b, a=None, z=None):
    return {k: s[k] - b[k] for k in months(s, b, a, z)}


def corr(x, y):
    ks = sorted(set(x) & set(y))
    a, b = [x[k] for k in ks], [y[k] for k in ks]
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va = sum((v - ma) ** 2 for v in a)
    vb = sum((v - mb) ** 2 for v in b)
    return round(sum((u - ma) * (v - mb) for u, v in zip(a, b)) / math.sqrt(va * vb), 3)


def main():
    res = {'angle': 'japan', 'role': '反証の検証（adversarial verifier）', 'researcher_file': 'out/mw_japan.json',
           'own_code': 'ポートフォリオの組み立て・超過・NW t（ラグ12）・CAGR・転がる窓・積立・Holm・線の当てはめは自前。mw_common は取得（get/jkp_rows/french_tables/ff_factors）だけ'}
    rj = json.load(open(os.path.join(M.BASE, 'out', 'mw_japan.json')))
    claimed = {r['id']: r for r in rj['tested']}

    def cl(i):
        r = claimed.get(i) or {}
        g = lambda k, f: (r.get(k) or {}).get(f)
        return {'grade': r.get('grade'), 'train_ex': g('train', 'ex_ann'), 'train_t': g('train', 't'), 'hold_ex': g('hold', 'ex_ann'),
                'hold_t': g('hold', 't'), 'hold_cagr_diff': g('hold', 'cagr_diff'), 'full_ex': g('full', 'ex_ann'), 'full_t': g('full', 't'),
                'roll20_win': g('roll20', 'win_rate'), 'net_cost_hold_ex': g('cost_hold', 'ex_ann'), 'holm_p': r.get('holm_p'),
                'family_size': r.get('family_size'), 'turnover': r.get('turnover')}

    # ── 相手 ──
    bj_usd = addrf({m: v for m, v in jmkt('jpn', 'vw').items() if m >= JKP0})
    bj_cap = addrf({m: v for m, v in jmkt('jpn', 'vw_cap').items() if m >= JKP0})
    frj = fr_region_mkt('Japan')
    fl = fr_block('Japan', 'Local')
    res['benchmark_checks'] = {
        'JKP_jpn_vw_vs_French_Japan_3F_Mkt_1990_07': {'corr': corr(bj_usd, frj), 'cagr_jkp': ex(bj_usd, frj, a=199007)['cagr_s'], 'cagr_french': ex(bj_usd, frj, a=199007)['cagr_b']},
        'JKP_jpn_vw_cap_minus_vw': {k: ex(bj_cap, bj_usd).get(k) for k in ('ex', 't', 'cagr_diff')},
        'JKP_jpn_vw_cap_minus_vw_hold': {k: ex(bj_cap, bj_usd, a=HOLD).get(k) for k in ('ex', 't', 'cagr_diff')},
        'verdict': 'JKP の vw 市場は French の日本の市場とほぼ同じ（上限なしの時価加重）。vw_cap 市場は vw より年+0.8%（全期間）高い＝ここでは vw を相手にしているので相手は弱くない',
        'excess_vs_total': 'JKP は三分位も市場も同じ米国の短期国債を引いた超過 → 両方に同じ RF を足している（混同なし）。French Intl は両方円建ての総リターン（混同なし）',
    }
    # 日本の市場 vs 米国の市場（文脈）
    us = M.ff_factors()['mkt']
    res['context_vs_SP500'] = {'JKP_jpn_mkt_vs_US_mkt_usd': ex(bj_usd, us), 'note': '事前登録は米国外なら同じ地域の市場を相手にしてよいと決めている＝ここは格付けに使わない文脈'}

    cands = {}
    # ── P_JKP_be_me ──
    be = [('be_me', side_of('be_me'))]
    s = cand_jkp(be)
    cands['P_JKP_be_me'] = (s, bj_usd, 0.6, 'USD', be, 'vw', 0, 'all', True)
    # ── P_JKP_B2 ──
    b2 = [('qmj', side_of('qmj')), ('be_me', side_of('be_me'))]
    cands['P_JKP_B2_quality_value'] = (cand_jkp(b2), bj_usd, 0.6, 'USD', b2, 'vw', 0, 'all', True)
    # ── French Intl ──
    for nm, cols in (('P_FR_BM_H', ['BM_H']), ('P_FR_VAL4', ['BM_H', 'EP_H', 'CEP_H', 'YLD_H']), ('P_FR_CEP_H', ['CEP_H']), ('P_FR_EP_H', ['EP_H'])):
        cands[nm] = (fr_mix(fl, cols), fl['Mkt'], 0.4, 'JPY', None, None, 0, 'all', False)
    # ── E6_ussel_t2 ──
    usel, ulog = us_select()
    usel_j = [(k, sd) for k, sd in usel if k in JP_KEYS]
    to_us = sum(census_turn(k) for k, _ in usel_j) / len(usel_j)
    cands['E6_ussel_t2'] = (cand_jkp(usel_j, nmin=30, need='half'), bj_usd, to_us, 'USD', usel_j, 'vw', 30, 'half', True)
    # ── E6_theme_Value ──
    cls = clusters()
    val = [(k, side_of(k)) for k in cls['Value'] if k in JP_KEYS]
    to_v = sum(census_turn(k) for k, _ in val) / len(val)
    cands['E6_theme_Value'] = (cand_jkp(val, nmin=30, need='half'), bj_usd, to_v, 'USD', val, 'vw', 30, 'half', True)
    # ── 研究側の JSON にある他の S/A（主張の一覧には無いが S/A）と B の上位2本 ──
    for nm, ks_, to_, w_ in (('E4_value_mom', ['be_me', 'ret_12_1'], (0.6 + 2.0) / 2, 'vw'),
                             ('E4_value_quality_mom', ['be_me', 'qmj', 'ret_12_1'], (0.6 + 0.6 + 2.0) / 3, 'vw'),
                             ('E4_def_value', ['be_me', 'ivol_capm_252d'], (0.6 + 0.8) / 2, 'vw'),
                             ('E2_JKPcap_div12m_me', ['div12m_me'], 0.6, 'vw_cap'),
                             ('E2_JKPcap_be_me', ['be_me'], 0.6, 'vw_cap'),
                             ('E3_bev_mev', ['bev_mev'], 0.8, 'vw'),
                             ('E2_JKPcap_B2_quality_value', ['qmj', 'be_me'], 0.6, 'vw_cap'),
                             ('E3_rd_me', ['rd_me'], 0.8, 'vw')):
        c_ = [(k, side_of(k)) for k in ks_]
        cands[nm] = (addrf(jcomp('jpn', c_, w_, 0, 'all')), bj_usd, to_, 'USD', c_, w_, 0, 'all', True)

    ids_map = {'P_JKP_be_me': 'P_JKP_be_me', 'P_JKP_B2_quality_value': 'P_JKP_B2_quality_value', 'P_FR_BM_H': 'P_FR_BM_H',
               'P_FR_VAL4': 'P_FR_VAL4', 'P_FR_CEP_H': 'P_FR_CEP_H', 'P_FR_EP_H': 'P_FR_EP_H', 'E6_ussel_t2': 'E6_ussel_t2',
               'E6_theme_Value': 'E6_theme_Value'}
    out = {}
    for nm, (s, b, to_, curr, comps, w_, nmin_, need_, isj) in cands.items():
        print('..', nm, flush=True)
        R = check(nm, s, b, to_, curr, cl(ids_map.get(nm, nm)), comps, w_ or 'vw', nmin_, need_, isj)
        if isj:
            sj, bjj = to_jpy(s), to_jpy(b)
            R['jpy'] = {'full': ex(sj, bjj), 'train': ex(sj, bjj, z=TRAIN_END), 'hold': ex(sj, bjj, a=HOLD)}
            R['vs_French_Japan_Mkt_usd'] = {'full': ex(s, frj), 'train': ex(s, frj, z=TRAIN_END), 'hold': ex(s, frj, a=HOLD)}
            R['tax_hold_jpy'] = tax_check(sj, bjj, to_)
            R['tax_hold_jpy_2x_turnover'] = tax_check(sj, bjj, 2 * to_)
            R['vs_US_market_usd_hold'] = ex(s, us, a=HOLD)
        else:
            R['tax_hold_jpy'] = tax_check(s, b, to_)
            R['tax_hold_jpy_2x_turnover'] = tax_check(s, b, 2 * to_)
        out[nm] = R
    res['candidates'] = out
    res['E6_us_selection'] = {'n_selected_us': len(usel), 'n_used_in_japan': len(usel_j), 'turnover_mean': round(to_us, 3),
                              'selected': usel_j,
                              'turnover_classes': {str(t): sum(1 for k, _ in usel_j if census_turn(k) == t) for t in (6.0, 2.5, 1.5, 0.8)},
                              'researcher_selected_same': sorted(map(tuple, claimed['E6_ussel_t2'].get('selected') or [])) == sorted(usel_j)}
    res['E6_value_members'] = val

    # ── 2022〜2025 が保有期間の累積の超過に占める割合（対数の超過）と 2013〜2021 ──
    for nm, (s, b, *_r) in cands.items():
        ks = months(s, b, HOLD)
        lx = {k: math.log1p(s[k]) - math.log1p(b[k]) for k in ks}
        tot_ = math.fsum(lx.values())
        late = math.fsum(v for k, v in lx.items() if k >= 202201)
        out[nm]['share_of_hold_log_excess_from_2022_25'] = round(late / tot_, 2) if tot_ else None
        out[nm]['sub']['2013-2021'] = ex(s, b, 201301, 202112)

    # ── 多重検定: 角度の全本数（E5/E8 の報告を除く）で保有期間の p を Holm ──
    allp = {r['id']: (r.get('hold') or {}).get('p') for r in rj['tested'] if r.get('family') not in ('E5', 'E8') and not r.get('error')}
    for nm, R in out.items():
        if nm in allp and R['hold']:
            allp[nm] = R['hold']['p']
    hp = holm(allp)
    n_all = len([p for p in allp.values() if p is not None])
    z_bonf = None
    lo, hi = 0.0, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if math.erfc(mid / math.sqrt(2)) * n_all > 0.05:
            lo = mid
        else:
            hi = mid
    z_bonf = round(hi, 2)
    res['multiple_testing'] = {'n_tests_in_angle': n_all, 'bonferroni_t_for_full_period_at_angle_level': z_bonf,
                               'holm_angle_wide_hold_p': {nm: hp.get(nm) for nm in out},
                               'researcher_family_holm_p': {nm: out[nm]['claimed'].get('holm_p') for nm in out},
                               'researcher_family_size': {nm: out[nm]['claimed'].get('family_size') for nm in out},
                               'n_value_family_S_in_json': sum(1 for r in rj['tested'] if r.get('grade') == 'S')}

    # ── 同じ賭けか: 保有期間の月次の超過の相関 ──
    exs = {nm: excess_series(cands[nm][0], cands[nm][1], HOLD) for nm in cands}
    names = ['P_JKP_be_me', 'P_FR_BM_H', 'P_FR_VAL4', 'P_FR_CEP_H', 'P_FR_EP_H', 'E6_theme_Value', 'P_JKP_B2_quality_value', 'E6_ussel_t2']
    res['excess_correlation_hold'] = {a: {b_: corr(exs[a], exs[b_]) for b_ in names if b_ != a} for a in names}

    # ── 他の国で保有期間（2007〜）だけでも勝ったか（C5 は全期間で測られていた） ──
    print('.. 他国の再現（保有期間）', flush=True)
    rep = {}
    rep['P_JKP_be_me'] = repl_hold_jkp([('be_me', '3.0')])
    rep['P_JKP_B2_quality_value'] = repl_hold_jkp(b2)
    rep['E2_JKPcap_div12m_me'] = repl_hold_jkp([('div12m_me', '3.0')], 'vw_cap')
    rep['E4_value_mom'] = repl_hold_jkp([('be_me', '3.0'), ('ret_12_1', '3.0')])
    rep['E4_value_quality_mom'] = repl_hold_jkp([('be_me', '3.0'), ('qmj', '3.0'), ('ret_12_1', '3.0')])
    rep['E4_def_value'] = repl_hold_jkp([('be_me', '3.0'), ('ivol_capm_252d', '1.0')])
    rep['E6_ussel_t2'] = repl_hold_jkp(usel_j, 'vw', 10, 'half')
    rep['E6_theme_Value'] = repl_hold_jkp(val, 'vw', 10, 'half')
    rep['E2_JKPcap_be_me'] = repl_hold_jkp([('be_me', '3.0')], 'vw_cap')
    rep['E3_bev_mev'] = repl_hold_jkp([('bev_mev', side_of('bev_mev'))])
    rep['E2_JKPcap_B2_quality_value'] = repl_hold_jkp(b2, 'vw_cap')
    rep['E3_rd_me'] = repl_hold_jkp([('rd_me', side_of('rd_me'))])
    for nm, cols in (('P_FR_BM_H', ['BM_H']), ('P_FR_VAL4', ['BM_H', 'EP_H', 'CEP_H', 'YLD_H']), ('P_FR_CEP_H', ['CEP_H']), ('P_FR_EP_H', ['EP_H'])):
        rep[nm] = repl_hold_fr(cols)
    for nm in rep:
        if nm in out:
            out[nm]['repl_full_and_hold'] = {k: v for k, v in rep[nm].items() if k != 'detail'}
            out[nm]['repl_detail'] = rep[nm]['detail']

    # ── 大型株だけ（French の 6/25分割・米ドル・vs French Japan Mkt） ──
    print('.. 大型株', flush=True)
    six = fr_tab('Japan_6_Portfolios_ME_BE-ME', 'Value Weighted Returns -- Monthly')
    six = {c: {m: v / 100 for m, v in x.items()} for c, x in six.items()}
    big = {}
    big['FR6_BIG_HiBM'] = six['BIG HiBM']
    big['FR6_SMALL_HiBM'] = six['SMALL HiBM']
    big['FR25_ME5_BM5'] = fr25_vw('Japan', ['BIG HiBM'])
    big['FR25_allsize_BM5_vw'] = fr25_vw('Japan', ['SMALL HiBM', 'ME2 BM5', 'ME3 BM5', 'ME4 BM5', 'BIG HiBM'])
    big['FR25_allsize_BM45_vw'] = fr25_vw('Japan', ['ME1 BM4', 'SMALL HiBM', 'ME2 BM4', 'ME2 BM5', 'ME3 BM4', 'ME3 BM5', 'ME4 BM4', 'ME4 BM5', 'ME5 BM4', 'BIG HiBM'])
    big['FR25_ME45_BM45_vw'] = fr25_vw('Japan', ['ME4 BM4', 'ME4 BM5', 'ME5 BM4', 'BIG HiBM'])
    allcells = list(fr_tab('Japan_25_Portfolios_ME_BE-ME', 'Number of Firms'))
    big['FR25_reconstructed_market_check'] = fr25_vw('Japan', allcells)
    bs = {}
    for nm, s in big.items():
        bs[nm] = {'full': ex(s, frj), 'train': ex(s, frj, z=TRAIN_END), 'hold': ex(s, frj, a=HOLD), 'hold_2007_2021': ex(s, frj, HOLD, 202112),
                  'roll10_in_hold': roll(s, frj, 10, a=HOLD)}
    bs['cap_share_of_BIG_HiBM_and_ME45_BM45'] = {'BIG_HiBM': fr25_weight_share('Japan', ['BIG HiBM'], at=[199106, 200706, 202506]),
                                                 'ME45_BM45': fr25_weight_share('Japan', ['ME4 BM4', 'ME4 BM5', 'ME5 BM4', 'BIG HiBM'], at=[199106, 200706, 202506]),
                                                 'allsize_BM5': fr25_weight_share('Japan', ['SMALL HiBM', 'ME2 BM5', 'ME3 BM5', 'ME4 BM5', 'BIG HiBM'], at=[199106, 200706, 202506])}
    res['large_cap_checks'] = bs

    # ── French の隣の定義（Required 表・米ドル表） ──
    frq, frd = fr_block('Japan', 'Local', 'Required'), fr_block('Japan', 'Dollar')
    nb = {}
    for nm, cols in (('BM_H', ['BM_H']), ('VAL4', ['BM_H', 'EP_H', 'CEP_H', 'YLD_H']), ('CEP_H', ['CEP_H']), ('EP_H', ['EP_H']), ('YLD_H', ['YLD_H'])):
        for tag, d_ in (('Local_NotReqd', fl), ('Local_Required', frq), ('Dollar_NotReqd', frd)):
            s = fr_mix(d_, cols)
            nb[f'{nm}_{tag}'] = {'full': ex(s, d_['Mkt']), 'train': ex(s, d_['Mkt'], z=TRAIN_END), 'hold': ex(s, d_['Mkt'], a=HOLD),
                                 'hold_2007_2021': ex(s, d_['Mkt'], HOLD, 202112)}
    # 配当の差（配当抜きの表から）: 高 B/M と市場の配当利回り（年・保有期間）
    wl = fr_block('Japan', 'Local', wout=True)
    divy = {}
    for c in ('Mkt', 'BM_H', 'YLD_H', 'EP_H', 'CEP_H'):
        ks = [k for k in sorted(set(fl[c]) & set(wl[c])) if k >= HOLD]
        divy[c] = round(math.fsum(fl[c][k] - wl[c][k] for k in ks) / len(ks) * 1200, 2)
    nb['dividend_yield_hold_pct'] = divy
    nb['dividend_tax_drag_BM_H_vs_Mkt_pct_per_year'] = round(TAX * (divy['BM_H'] - divy['Mkt']), 2)
    res['french_neighbors'] = nb

    # ── E6_ussel の隣の変数（選択の閾値・n の下限・そろう割合・米国の選択期間） ──
    print('.. E6 の隣', flush=True)
    e6n = {}
    for thr in (1.65, 2.5, 3.0):
        sel_, _ = us_select(thr=thr)
        sj = [(k, sd) for k, sd in sel_ if k in JP_KEYS]
        s = cand_jkp(sj, nmin=30, need='half')
        e6n[f'thr_{thr}'] = {'n': len(sj), 'full': ex(s, bj_usd), 'train': ex(s, bj_usd, z=TRAIN_END), 'hold': ex(s, bj_usd, a=HOLD)}
    for nmin in (10, 50, 100):
        s = cand_jkp(usel_j, nmin=nmin, need='half')
        e6n[f'nmin_{nmin}'] = {'full': ex(s, bj_usd), 'train': ex(s, bj_usd, z=TRAIN_END), 'hold': ex(s, bj_usd, a=HOLD)}
    s = cand_jkp(usel_j, nmin=30, need=0.75)
    e6n['need_75pct'] = {'full': ex(s, bj_usd), 'train': ex(s, bj_usd, z=TRAIN_END), 'hold': ex(s, bj_usd, a=HOLD)}
    sel_, _ = us_select(a=197301)
    sj = [(k, sd) for k, sd in sel_ if k in JP_KEYS]
    s = cand_jkp(sj, nmin=30, need='half')
    e6n['us_select_1973_2006'] = {'n': len(sj), 'full': ex(s, bj_usd), 'train': ex(s, bj_usd, z=TRAIN_END), 'hold': ex(s, bj_usd, a=HOLD)}
    plc = [(k, sd) for k, _ in usel_j for sd in ('1.0', '2.0', '3.0')]
    s_pl = cand_jkp(plc, nmin=30, need='half')
    s_e6 = cands['E6_ussel_t2'][0]
    e6n['placebo_all_terciles_vs_mkt'] = {'train': ex(s_pl, bj_usd, z=TRAIN_END), 'hold': ex(s_pl, bj_usd, a=HOLD)}
    e6n['strategy_vs_placebo'] = {'train': ex(s_e6, s_pl, z=TRAIN_END), 'hold': ex(s_e6, s_pl, a=HOLD), 'full': ex(s_e6, s_pl)}
    # 割安クラスタを除いた米国選択（割安の賭けと別物か）
    vset = set(cls['Value'])
    nv = [(k, sd) for k, sd in usel_j if k not in vset]
    s = cand_jkp(nv, nmin=30, need='half')
    e6n['excluding_Value_cluster'] = {'n': len(nv), 'full': ex(s, bj_usd), 'train': ex(s, bj_usd, z=TRAIN_END), 'hold': ex(s, bj_usd, a=HOLD),
                                      'hold_2007_2021': ex(s, bj_usd, HOLD, 202112)}
    e6n['n_components_available_by_year'] = {y: sum(1 for k, sd in usel_j if (jpf('jpn', k) or {}).get(sd, {}).get(y * 100 + 6, (0, 0))[1] >= 30) for y in (1988, 1989, 1990, 1995, 2000, 2006, 2015, 2025)}
    res['E6_ussel_neighbors'] = e6n

    # ── E6_theme_Value の隣 ──
    tv = {}
    for nmin in (10, 29, 31, 50):
        s = cand_jkp(val, nmin=nmin, need='half')
        tv[f'nmin_{nmin}'] = {'full': ex(s, bj_usd, raw_t=True), 'hold': ex(s, bj_usd, a=HOLD)}
        tv[f'nmin_{nmin}']['full']['t_raw'] = round(tv[f'nmin_{nmin}']['full']['t_raw'], 4)
    s = cands['E6_theme_Value'][0]
    tv['jpy_full'] = ex(to_jpy(s), to_jpy(bj_usd), raw_t=True)
    tv['jpy_full']['t_raw'] = round(tv['jpy_full']['t_raw'], 4)
    tv['vs_French_mkt_full_from_1990_07'] = ex(s, frj)
    res['E6_theme_Value_neighbors'] = tv

    # ── 質(QMJ)を含む合成: QMJ の三分位は 1993-03 まで 3〜7 銘柄 → n≥30 の月だけ・半分以上そろう月（隣の定義）で訓練期間 ──
    qn = {}
    for nm, ks_, w_ in (('P_JKP_B2_quality_value', ['qmj', 'be_me'], 'vw'), ('E4_value_quality_mom', ['be_me', 'qmj', 'ret_12_1'], 'vw'),
                        ('E2_JKPcap_B2_quality_value', ['qmj', 'be_me'], 'vw_cap')):
        c_ = [(k, side_of(k)) for k in ks_]
        s_all30 = addrf(jcomp('jpn', c_, w_, 30, 'all'))
        s_half30 = addrf(jcomp('jpn', c_, w_, 30, 'half' if len(c_) > 2 else 0.99))
        qn[nm] = {'n30_all_train': ex(s_all30, bj_usd, z=TRAIN_END), 'n30_all_full': ex(s_all30, bj_usd),
                  'n30_2of3_train': ex(addrf(jcomp('jpn', c_, w_, 30, 'half')), bj_usd, z=TRAIN_END) if len(c_) > 2 else None,
                  'qmj_n_first_ge30': min((m for m, (r, n) in jpf('jpn', 'qmj', w_)['3.0'].items() if n >= 30), default=None)}
    res['qmj_thin_early_checks'] = qn

    # ── 偽薬: 同じ特徴の3つの三分位を全部等分に持つ（三分位を等分に混ぜる形そのものの傾き）と、それに対する上乗せ ──
    plc_out = {}
    for nm, ks_, w_, nmin_, need_ in (('P_JKP_be_me', ['be_me'], 'vw', 0, 'all'), ('P_JKP_B2_quality_value', ['qmj', 'be_me'], 'vw', 0, 'all'),
                                      ('E4_value_quality_mom', ['be_me', 'qmj', 'ret_12_1'], 'vw', 0, 'all'),
                                      ('E4_value_mom', ['be_me', 'ret_12_1'], 'vw', 0, 'all')):
        c_ = [(k, side_of(k)) for k in ks_]
        pl = [(k, sd) for k in ks_ for sd in ('1.0', '2.0', '3.0')]
        s_ = addrf(jcomp('jpn', c_, w_, nmin_, need_))
        p_ = addrf(jcomp('jpn', pl, w_, nmin_, need_))
        plc_out[nm] = {'placebo_vs_mkt_hold': ex(p_, bj_usd, a=HOLD), 'strategy_vs_placebo_hold': ex(s_, p_, a=HOLD),
                       'strategy_vs_placebo_train': ex(s_, p_, z=TRAIN_END), 'strategy_vs_placebo_full': ex(s_, p_)}
    res['placebo_checks'] = plc_out

    # ── 公表後（日本の B/M 効果は Chan・Hamao・Lakonishok 1991 で公表 → 1992-01〜）: 研究側に有利な側の答え合わせも載せる ──
    pp = {}
    for nm in ('P_JKP_be_me', 'P_FR_BM_H', 'P_FR_VAL4', 'E2_JKPcap_div12m_me'):
        s_, b_ = cands[nm][0], cands[nm][1]
        pp[nm] = {'1992_2025': ex(s_, b_, a=199201), '1992_2006': ex(s_, b_, 199201, TRAIN_END)}
    res['post_publication_CHL1991'] = pp

    # ── 自前の格付け（研究側の C5・族の Holm をそのまま使う版／厳しい版） ──
    fam_holm = {nm: out[nm]['claimed'].get('holm_p') for nm in out}
    for nm, R in out.items():
        cr = claimed.get(nm) or {}
        rp = cr.get('repl') or {}
        g0, c0 = my_grade(R['full'], R['train'], R['hold'], R['roll20'], R['cost_hold_010'], rp.get('positive'), rp.get('regions'), fam_holm.get(nm))
        R['my_grade_as_registered'] = {'grade': g0, 'criteria': c0}
        # 厳しい版1: 角度の全本数で Holm（全期間 t≥3 はそのまま）
        g1, c1 = my_grade(R['full'], R['train'], R['hold'], R['roll20'], R['cost_hold_010'], rp.get('positive'), rp.get('regions'), hp.get(nm))
        # 厳しい版2: 訓練期間は n≥30 の月だけ（15年未満は C1 不合格）
        trn = R.get('train_n30') or R['train']
        g2, c2 = my_grade(R['full'], trn, R['hold'], R['roll20'], R['cost_hold_010'], rp.get('positive'), rp.get('regions'), fam_holm.get(nm))
        # 厳しい版3: 保有期間を 2022-12 で切る（東証の PBR 要請・日銀の正常化の前）
        h3 = R['sub']['hold_to_2022_before_TSE_PBR_request']
        g3, c3 = my_grade(R['full'], R['train'], h3, R['roll20'], ex(cost(cands[nm][0], cands[nm][2], COST), cands[nm][1], HOLD, 202212), rp.get('positive'), rp.get('regions'), fam_holm.get(nm))
        # 厳しい版4: 1998-2000 を抜く（全期間 t・訓練）。15年の下限は暦の長さで見る（抜いた3年で下限に触れさせない）
        tr4 = dict(R['sub']['train_excl_1998_2000']) if R['sub']['train_excl_1998_2000'] else None
        if tr4 and tr4['from'] <= 199801:
            tr4['years'] = round(tr4['years'] + 3, 2)
        g4, c4 = my_grade(R['sub']['full_excl_1998_2000'], tr4, R['hold'], R['roll20'], R['cost_hold_010'], rp.get('positive'), rp.get('regions'), fam_holm.get(nm))
        # 厳しい版5: C5 を保有期間の他国の再現で
        rr = (R.get('repl_full_and_hold') or {})
        g5, c5 = my_grade(R['full'], R['train'], R['hold'], R['roll20'], R['cost_hold_010'], rr.get('hold_pos'), rr.get('n'), fam_holm.get(nm)) if rr else (None, None)
        R['stress_grades'] = {'angle_wide_holm': g1, 'train_n30_min15y': g2, 'hold_cut_2022_12': g3, 'drop_1998_2000': g4, 'C5_on_holdout_only': g5}

    res['general_checks'] = {
        'reproduction': '16本すべてで訓練・保有・全期間の超過と NW t、CAGR の差、転がる20年、積立20年、費用後の保有期間が研究側の JSON と一致（E6 の米国選択61特徴も同一）',
        'benchmark': res['benchmark_checks']['verdict'],
        'excess_vs_total': res['benchmark_checks']['excess_vs_total'],
        'good_side': '良い側は JKP usa all_factors の direction（原論文の符号）か French の High（割安側）で、日本の保有期間を見て選んでいない。E3 の jpside は日本の訓練期間だけで選ぶ。E6_ussel は米国の 1963-07〜2006-12 だけで選ぶ（自前で再選択して一致）',
        'look_ahead_in_design': '主の族の設計そのもの（日本・割安）は、2026-09-26 に測った日本の割安の 2007〜 の成績を見て選ばれている（事前登録の context に明記）。第2の事前登録（E6・E7）は第1回の結果（割安が S）を見た後',
        'survivorship': 'JKP・French は上場廃止を含む。ただし JKP 日本は 1987〜88 年の三分位が 6〜13 銘柄（Compustat Global の初期の薄さ・後から足された会社の偏りの可能性）、French Intl の 2006 年までは MSCI の対象（大型約500社）。n≥30 の月だけでも be_me の訓練は +7.86 t2.99 で結論は変わらない',
        'costs_taxes': '費用の損益分岐（片道100%あたり）は割安で 4〜10%、E6_ussel で 0.91%。課税口座（売却益 20.315%・回転ぶん毎月・相手の ETF は最後に一度）の CAGR 差は各候補の tax_hold_jpy。配当課税の差は高 B/M と市場の配当利回りの差 ' + str(res['french_neighbors']['dividend_yield_hold_pct']['BM_H'] - res['french_neighbors']['dividend_yield_hold_pct']['Mkt'])[:4] + '%×20.315%＝年 ' + str(res['french_neighbors']['dividend_tax_drag_BM_H_vs_Mkt_pct_per_year']) + '% で小さい',
        'effective_bets': '主張の S 8本（＋JSON の S/A 6本）は実質3つの賭け: ①日本の割安（be_me・bev_mev・BM/EP/CEP/VAL4・テーマ Value・上限つき版・def_value・value_mom＝保有期間の超過の相関 0.68〜0.93）②割安＋質（＋勢い）③米国で選んだ多数の信号の合成（割安との相関 0.05〜0.31）',
        'context_not_graded': '相手は日本の市場（事前登録どおり）。日本の市場そのものは米国の市場に 1987〜2025 で年 ' + str(res['context_vs_SP500']['JKP_jpn_mkt_vs_US_mkt_usd']['cagr_diff']) + '%（CAGR 差・米ドル）負けており、日本の割安の最良の候補でも保有期間は米国の市場に負けている',
    }
    res['verdicts'] = verdicts(res, rj)
    res['summary_ja'] = SUMMARY_JA
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
    return res


def _f(x):
    return 'なし' if not x else f"{x['ex']:+.2f}%/年 t{x['t']}"


def verdicts(res, rj):
    C = res['candidates']
    MT = res['multiple_testing']
    RP = lambda nm: C[nm].get('repl_full_and_hold') or {}
    LC = res['large_cap_checks']
    FN = res['french_neighbors']
    E6N = res['E6_ussel_neighbors']
    TV = res['E6_theme_Value_neighbors']
    QN = res['qmj_thin_early_checks']
    PL = res['placebo_checks']
    PP = res['post_publication_CHL1991']

    def key(nm):
        c = C[nm]
        return (f"再現: 訓練 {_f(c['train'])}・保有 {_f(c['hold'])}（CAGR差 {c['hold']['cagr_diff']:+.2f}）・全期間 {_f(c['full'])}・"
                f"費用後の保有 {_f(c['cost_hold_010'])}・転がる20年 {c['roll20']['wins']}/{c['roll20']['windows']}"
                f"｜2007-2021 {_f(c['sub']['hold_2007_2021'])}・2022-12まで {_f(c['sub']['hold_to_2022_before_TSE_PBR_request'])}・"
                f"2013-2021 {_f(c['sub']['2013-2021'])}・保有期間内の10年窓 {c['roll10_in_hold']['wins']}/{c['roll10_in_hold']['windows']}")

    contam = ('保有期間は盲検ではない: 2026-09-26（事前登録の2日前）の out/jkp_evidence.json・out/factor_evidence.json に日本の割安の 2007〜 の成績が'
              '既に載っていた（割安テーマ +3.32 t2.08・配当利回り +6.16 t2.98・French 日本 HML +4.26 t1.76）。事前登録の context もそれを引いている')
    period = lambda nm: (f"保有期間の t≥1.65 は 2022〜2025（東証の PBR 要請・日銀の正常化・世界の割安の戻り）に依る: 保有期間の対数の超過の "
                         f"{int(round(C[nm]['share_of_hold_log_excess_from_2022_25'] * 100))}% がこの4年。2007-2021 は {_f(C[nm]['sub']['hold_2007_2021'])}")
    abroad = lambda nm: (f"他国の保有期間（C5 は全期間で測られていた）: 正 {RP(nm).get('hold_pos')}/{RP(nm).get('n')}（t≥1.65 は {RP(nm).get('hold_pos_t165')}）、"
                         f"2007-2021 だけだと正 {RP(nm).get('hold_2007_2021_pos')}/{RP(nm).get('n')}")
    V = []

    def add(nm, claimed, verdict, vg, issues):
        c = C[nm]
        V.append({'name': nm, 'claimed_grade': claimed, 'verified_grade': vg, 'verdict': verdict, 'reproduced': True,
                  'key_numbers': key(nm), 'issues': issues,
                  'stress_grades': c['stress_grades'], 'angle_wide_holm_p': MT['holm_angle_wide_hold_p'].get(nm)})

    big = LC['FR6_BIG_HiBM']
    add('P_JKP_be_me', 'S', 'downgraded to B', 'B', [
        contam, period('P_JKP_be_me'), abroad('P_JKP_be_me') + '（2/3 に届かない）',
        f"大型株だけ（French 6分割 BIG HiBM）: 保有 {_f(big['hold'])}・2007-2021 {_f(big['hold_2007_2021'])}＝実際に買える大型の割安は保有期間で有意に勝っていない",
        f"French の割安とは同じ賭け（保有期間の月次の超過の相関 {res['excess_correlation_hold']['P_JKP_be_me']['P_FR_BM_H']}）＝『独立の2つのデータで同じ結論』は独立の確認ではない",
        f"多重検定: 角度の {MT['n_tests_in_angle']} 本で Holm すると保有期間 p→{MT['holm_angle_wide_hold_p']['P_JKP_be_me']}。C7 は全期間 t {C['P_JKP_be_me']['full']['t']}（HLZ の 3.0）だけで通る（角度の Bonferroni 線は {MT['bonferroni_t_for_full_period_at_angle_level']}）",
        f"研究側に有利な点も確認: 公表後（Chan-Hamao-Lakonishok 1991 → 1992〜2025）{_f(PP['P_JKP_be_me']['1992_2025'])}・円建て {_f(C['P_JKP_be_me']['jpy']['hold'])}・French の市場相手 {_f(C['P_JKP_be_me']['vs_French_Japan_Mkt_usd']['hold'])}・費用2倍×0.30% {_f(C['P_JKP_be_me']['cost_hold_2x_030'])}・課税口座でも CAGR差 {C['P_JKP_be_me']['tax_hold_jpy']['after_tax_cagr_diff']:+.2f}・偽薬に対して保有 {_f(PL['P_JKP_be_me']['strategy_vs_placebo_hold'])}",
        'C3（2022-25 抜きで不成立）と C5（保有期間の他国で 2/3 未満）の両方が頑丈でない → A の条件（C3 か C5）を満たさない'])
    add('P_FR_BM_H', 'S', 'downgraded to B', 'B', [
        contam, period('P_FR_BM_H'), abroad('P_FR_BM_H') + '＝保有期間の他国の勝ちも 2022〜 の世界の割安の戻りに依る',
        f"隣の表: Required {_f(FN['BM_H_Local_Required']['hold'])}・米ドル {_f(FN['BM_H_Dollar_NotReqd']['hold'])}・保有期間内の10年窓 {C['P_FR_BM_H']['roll10_in_hold']['wins']}/{C['P_FR_BM_H']['roll10_in_hold']['windows']}",
        '保有期間の始まり（2007）で母集団が MSCI の大型約500社から Bloomberg の約3,000社へ替わる＝保有期間は別の母集団',
        f"JKP の be_me と同じ賭け（相関 {res['excess_correlation_hold']['P_FR_BM_H']['P_JKP_be_me']}）",
        f"研究側に有利な点: 公表後 1992〜2025 {_f(PP['P_FR_BM_H']['1992_2025'])}・転がる20年 31/31・1998-2000 を抜いても全期間 {_f(C['P_FR_BM_H']['sub']['full_excl_1998_2000'])}"])
    add('P_FR_VAL4', 'S', 'downgraded to B', 'B', [
        contam, period('P_FR_VAL4'), abroad('P_FR_VAL4') + '（2007-2021 の 14/20＝70% は 2/3 の線をわずかに越えるだけ・有意は 2/20）',
        f"BM_H と同じ賭け（相関 {res['excess_correlation_hold']['P_FR_VAL4']['P_FR_BM_H']}）。保有期間の前半 {_f(C['P_FR_VAL4']['sub']['hold_1st_half'])}／後半 {_f(C['P_FR_VAL4']['sub']['hold_2nd_half'])}",
        '境目は A: 他国の 2007-2021 の 70% を C5 と認めれば A。懐疑を既定にして B とした'])
    add('P_FR_CEP_H', 'S', 'downgraded to B', 'B', [
        f"C1 が 1998-2000 に依る: 抜くと訓練 {_f(C['P_FR_CEP_H']['sub']['train_excl_1998_2000'])}（t<2.0）・全期間 {_f(C['P_FR_CEP_H']['sub']['full_excl_1998_2000'])}（t<3.0）",
        f"C3 は線の上ぎりぎり: 登録 {C['P_FR_CEP_H']['hold']['t']}・Required 表 {_f(FN['CEP_H_Local_Required']['hold'])}・米ドル表 {_f(FN['CEP_H_Dollar_NotReqd']['hold'])}・費用2倍×0.30% {_f(C['P_FR_CEP_H']['cost_hold_2x_030'])}",
        period('P_FR_CEP_H'), contam, 'JKP・French の割安と同じ賭け'])
    add('P_FR_EP_H', 'S', 'downgraded to B', 'B', [
        f"C7 が脆い: 米ドル表の全期間 {_f(FN['EP_H_Dollar_NotReqd']['full'])}・1998-2000 を抜くと {_f(C['P_FR_EP_H']['sub']['full_excl_1998_2000'])}（t<3.0）、族の Holm は {C['P_FR_EP_H']['claimed']['holm_p']}",
        f"C3 が脆い: 登録 {C['P_FR_EP_H']['hold']['t']}（線1.65のすぐ上）・米ドル表 {_f(FN['EP_H_Dollar_NotReqd']['hold'])}・費用2倍×0.30% {_f(C['P_FR_EP_H']['cost_hold_2x_030'])}",
        period('P_FR_EP_H') + f"・保有期間の前半 {_f(C['P_FR_EP_H']['sub']['hold_1st_half'])}", contam])
    q = QN['P_JKP_B2_quality_value']
    add('P_JKP_B2_quality_value', 'S', 'downgraded to B', 'B', [
        f"C1 が脆い: QMJ の三分位は {q['qmj_n_first_ge30']} まで 3〜19 銘柄。30銘柄以上の月だけだと訓練 {_f(q['n30_all_train'])}・{q['n30_all_train']['years']}年（15年の下限未満）。1998-2000 を抜くと訓練 {_f(C['P_JKP_B2_quality_value']['sub']['train_excl_1998_2000'])}（t<2.0）",
        f"C7 は族（P の20本）の Holm {C['P_JKP_B2_quality_value']['claimed']['holm_p']} だけで通る（全期間 t {C['P_JKP_B2_quality_value']['full']['t']}<3.0）。角度の全 {MT['n_tests_in_angle']} 本の Holm では {MT['holm_angle_wide_hold_p']['P_JKP_B2_quality_value']}",
        'QMJ の定義は 2013/2019 年の論文（標本に日本の 1989〜2012 を含む）＝保有期間の最初の6年は設計の段階で見られていた',
        f"保有期間は頑丈（ここは研究側が正しい）: 2007-2021 {_f(C['P_JKP_B2_quality_value']['sub']['hold_2007_2021'])}・3区間とも正・10年窓 9/9・他国の保有期間 正 {RP('P_JKP_B2_quality_value')['hold_pos']}/{RP('P_JKP_B2_quality_value')['n']}（t≥1.65 {RP('P_JKP_B2_quality_value')['hold_pos_t165']}）・偽薬に対して {_f(PL['P_JKP_B2_quality_value']['strategy_vs_placebo_hold'])}",
        'B の定義（保有期間でも費用後に勝つが統計の強さか頑丈さが足りない）に当たる。n≥30・15年の下限を厳格に当てれば C'])
    e6 = C['E6_ussel_t2']
    add('E6_ussel_t2', 'S', 'confirmed', 'S', [
        f"反証を試みたが崩れない: 3区間 2007-12 {_f(e6['sub']['2007-12'])}／2013-19 {_f(e6['sub']['2013-19'])}／2020- {_f(e6['sub']['2020-'])}、2022-25 抜き {_f(e6['sub']['hold_2007_2021'])}、前半 {_f(e6['sub']['hold_1st_half'])}／後半 {_f(e6['sub']['hold_2nd_half'])}、保有期間内の10年窓 9/9・5年窓 14/14",
        f"角度の全 {MT['n_tests_in_angle']} 本の Holm でも保有期間 p={MT['holm_angle_wide_hold_p']['E6_ussel_t2']}（<0.05）・全期間 t {e6['full']['t']}（角度の Bonferroni 線 {MT['bonferroni_t_for_full_period_at_angle_level']} を越える）",
        f"隣の変数: 選択の閾値 t≥1.65 {_f(E6N['thr_1.65']['hold'])}・t≥2.5 {_f(E6N['thr_2.5']['hold'])}・t≥3.0 {_f(E6N['thr_3.0']['hold'])}（ただし t≥3.0 は訓練 {_f(E6N['thr_3.0']['train'])} で C1 不合格）・n≥10/50/100 と 75%そろう月も同じ・米国の選択を 1973〜 にしても {_f(E6N['us_select_1973_2006']['hold'])}",
        f"割安の賭けではない: 割安クラスタを除いても保有 {_f(E6N['excluding_Value_cluster']['hold'])}・割安の候補との相関 0.05〜0.31。偽薬（三分位を全部等分）{_f(E6N['placebo_all_terciles_vs_mkt']['hold'])} に対して {_f(E6N['strategy_vs_placebo']['hold'])}",
        f"他国の保有期間: 正 {RP('E6_ussel_t2')['hold_pos']}/{RP('E6_ussel_t2')['n']}（t≥1.65 {RP('E6_ussel_t2')['hold_pos_t165']}）・2007-2021 も {RP('E6_ussel_t2')['hold_2007_2021_pos']}/{RP('E6_ussel_t2')['n']}",
        f"弱み（格付けは変えない）: 幅が小さい（年+1.2%・追従のぶれ {e6['hold']['te']}%）。費用を2倍×0.30%にすると {_f(e6['cost_hold_2x_030'])} で C3 を割る。課税口座（回転 {e6['turnover_used']:.2f}/年）だと CAGR差 {e6['tax_hold_jpy']['pre_tax_cagr_diff']:+.2f}→{e6['tax_hold_jpy']['after_tax_cagr_diff']:+.2f}。61特徴×全上場を毎月計算して千銘柄超を持つ形で、個人が買える商品は無い。相手は日本の市場で、米国の市場には保有期間で {_f(e6['vs_US_market_usd_hold'])}",
        '候補の153特徴そのものは 2023 年の論文の一覧（2006年より後に公表された特徴を含む）＝米国で選ぶ母集団に公表の後知恵が薄く入る（日本の保有期間には直接は漏れない）'])
    add('E6_theme_Value', 'S', 'downgraded to B', 'B', [
        f"C7 は髪の毛一本: 全期間 t={C['E6_theme_Value']['full_t_unrounded']}（丸めて 3.00）。n≥29 で {TV['nmin_29']['full']['t_raw']}・n≥50 で {TV['nmin_50']['full']['t_raw']}・French の市場を相手にすると {_f(TV['vs_French_mkt_full_from_1990_07'])}。族（E6 16本）の Holm は {C['E6_theme_Value']['claimed']['holm_p']}",
        '第2の事前登録（第1回で割安が勝ったのを見た後）で足した割安の言い換え。クラスタ表は 2023 年の論文（米国の全期間で作った分類）',
        period('E6_theme_Value'), contam])
    add('E4_value_quality_mom', 'S', 'confirmed', 'S', [
        f"主張の一覧には無いが研究側の JSON で S。反証を試みたが崩れない: 2007-2021 {_f(C['E4_value_quality_mom']['sub']['hold_2007_2021'])}・2022-12まで {_f(C['E4_value_quality_mom']['sub']['hold_to_2022_before_TSE_PBR_request'])}・前半 {_f(C['E4_value_quality_mom']['sub']['hold_1st_half'])}／後半 {_f(C['E4_value_quality_mom']['sub']['hold_2nd_half'])}・10年窓 9/9・円建て {_f(C['E4_value_quality_mom']['jpy']['hold'])}・費用2倍×0.30% {_f(C['E4_value_quality_mom']['cost_hold_2x_030'])}",
        f"他国の保有期間: 正 {RP('E4_value_quality_mom')['hold_pos']}/{RP('E4_value_quality_mom')['n']}（t≥1.65 {RP('E4_value_quality_mom')['hold_pos_t165']}）・2007-2021 も {RP('E4_value_quality_mom')['hold_2007_2021_pos']}/{RP('E4_value_quality_mom')['n']}。偽薬に対して {_f(PL['E4_value_quality_mom']['strategy_vs_placebo_hold'])}",
        f"脆い所: 登録どおりだと QMJ の足が 1993 まで 3〜7 銘柄（n≥30 全部そろう月だけなら訓練 {QN['E4_value_quality_mom']['n30_all_train']['years']}年＜15年）。隣の定義（n≥30・3本中2本以上）なら訓練 {_f(QN['E4_value_quality_mom']['n30_2of3_train'])}・{QN['E4_value_quality_mom']['n30_2of3_train']['years']}年で C1 は立つ",
        f"C7 は全期間 t {C['E4_value_quality_mom']['full']['t']}（HLZ）か族8本の Holm {C['E4_value_quality_mom']['claimed']['holm_p']} で通る。1998-2000 を抜き かつ 角度の全本数で Holm（{MT['holm_angle_wide_hold_p']['E4_value_quality_mom']}）の二重の厳しさを重ねた時だけ落ちる",
        'QMJ と「割安＋勢い」の組み合わせは 2013/2019 年の論文（標本に日本の 2007〜2012 を含む）＝保有期間の前の6年には設計の後知恵。2013 以降だけでも正（recent ' + _f(C['E4_value_quality_mom']['recent']) + '）'])
    add('E4_value_mom', 'S', 'downgraded to A', 'A', [
        period('E4_value_mom') + f"・2022-12まで {_f(C['E4_value_mom']['sub']['hold_to_2022_before_TSE_PBR_request'])}（C3 の線 1.65 を割る）",
        f"C5 は保有期間でも頑丈: 他国の保有期間 正 {RP('E4_value_mom')['hold_pos']}/{RP('E4_value_mom')['n']}（t≥1.65 {RP('E4_value_mom')['hold_pos_t165']}）・2007-2021 も {RP('E4_value_mom')['hold_2007_2021_pos']}/{RP('E4_value_mom')['n']} → A の条件（C3 か C5）は C5 で満たす",
        f"費用2倍×0.30% で {_f(C['E4_value_mom']['cost_hold_2x_030'])}（勢いの足の回転 2.0/年）", contam + '（割安の足）'])
    add('E4_def_value', 'A', 'downgraded to B', 'B', [
        f"C3 は元から不合格（{C['E4_def_value']['hold']['t']}）で A は C5 だけに依る。その C5 は保有期間だと 正 {RP('E4_def_value')['hold_pos']}/{RP('E4_def_value')['n']}（2/3 の線をわずかに越えるだけ・有意 {RP('E4_def_value')['hold_pos_t165']}）、2007-2021 は {RP('E4_def_value')['hold_2007_2021_pos']}/{RP('E4_def_value')['n']}",
        period('E4_def_value') + f"・保有期間内の10年窓 {C['E4_def_value']['roll10_in_hold']['wins']}/{C['E4_def_value']['roll10_in_hold']['windows']}"])
    add('E2_JKPcap_div12m_me', 'S', 'downgraded to B', 'B', [
        '上限なし（事前登録の主の定義）の同じ特徴 P_JKP_div12m_me は C（訓練 t1.78）。S は報告用の族（上限つき）でだけ出る＝重みの付け方の隣で C1 が割れる',
        f"上限つきそのものが日本では強かった: vw_cap 市場 − vw 市場 = 全期間 {res['benchmark_checks']['JKP_jpn_vw_cap_minus_vw']['ex']:+.2f}%/年・保有期間 {res['benchmark_checks']['JKP_jpn_vw_cap_minus_vw_hold']['ex']:+.2f}%/年＝超過の一部は配当ではなく上限の効果",
        '保有期間は盲検ではない: 日本の配当利回り因子の 2007〜 +6.16 t2.98 は 2026-09-26 に測定済み',
        f"保有期間そのものは頑丈: 2007-2021 {_f(C['E2_JKPcap_div12m_me']['sub']['hold_2007_2021'])}・10年窓 9/9・他国の保有期間 正 {RP('E2_JKPcap_div12m_me')['hold_pos']}/{RP('E2_JKPcap_div12m_me')['n']}"])
    add('E2_JKPcap_be_me', 'S', 'downgraded to B', 'B', [
        'P_JKP_be_me の上限つき版＝同じ賭け。' + period('E2_JKPcap_be_me'), abroad('E2_JKPcap_be_me'), contam])
    add('E3_bev_mev', 'S', 'downgraded to B', 'B', [
        f"C7 が脆い: 族（E3 209本）の Holm 1.0、1998-2000 を抜くと全期間 {_f(C['E3_bev_mev']['sub']['full_excl_1998_2000'])}（t<3.0）", period('E3_bev_mev'), abroad('E3_bev_mev'), 'be_me と同じ賭け', contam])
    add('E2_JKPcap_B2_quality_value', 'B', 'confirmed', 'B', [
        f"B の上位（保有 {_f(C['E2_JKPcap_B2_quality_value']['hold'])}）。B の条件（C1・C2・C6）は登録どおり満たす。保有期間は頑丈（2007-2021 {_f(C['E2_JKPcap_B2_quality_value']['sub']['hold_2007_2021'])}・他国 {RP('E2_JKPcap_B2_quality_value')['hold_pos']}/{RP('E2_JKPcap_B2_quality_value')['n']}）",
        f"ただし C1 は QMJ の薄い初期に依る: n≥30 の月だけだと訓練 {_f(QN['E2_JKPcap_B2_quality_value']['n30_all_train'])}・{QN['E2_JKPcap_B2_quality_value']['n30_all_train']['years']}年＝厳格なら C"])
    add('E3_rd_me', 'B', 'confirmed', 'B', [
        f"B の2番目（保有 {_f(C['E3_rd_me']['hold'])}）。B の条件は登録どおり満たし、どの厳しい版でも B のまま",
        f"ただし全数 {sum(1 for r in rj['tested'] if r.get('family') == 'E3' and not r.get('error'))} 本のうち訓練で C1 を通ったのは5本（偶然でも約5本）で、rd_me（研究開発÷時価）は割安の仲間。保有期間の前半 {_f(C['E3_rd_me']['sub']['hold_1st_half'])}／後半 {_f(C['E3_rd_me']['sub']['hold_2nd_half'])}＝勝ちは 2016 年以降"])
    return V


SUMMARY_JA = """japan 角度の S/A 候補16本（主張の8本、JSON にある他の S/A 6本、B の上位2本）を自前のコードで作り直しました。数字は16本とも研究側と一致しました。相手は上限なしの時価加重で、超過と総リターンの混同もありません。
主張の S 8本のうち確認できたのは E6_ussel_t2（米国の2006年までのデータで選んだ61特徴の合成）だけです。保有期間は年+1.2%・t3.8 で、3区間、2022-25年を抜いた場合、隣の変数、他国19/19、角度全体278本の Holm（p=0.042）のどれでも崩れませんでした。ただし幅が小さく、個人が買える形はありません。課税口座では CAGR差が約半分になります。
割安の S 6本（JKP be_me、French の BM/VAL4/CEP/EP、テーマ Value）と質＋割安（B2）は B に下げました。理由は次の4つです。
(1) 日本の割安の2007年以降の成績は、事前登録の2日前に測定済みでした（保有期間は盲検ではない）。
(2) 保有期間の t は2022〜2025年に依存しています（be_me は2007-2021年だと +1.9% t1.0、2013-2021年は −1.2%/年）。他国の割安も2007-2021年に勝ったのは10/19・10/20だけです。
(3) 大型株だけの割安は2007-2021年に負けています。JKP と French は同じ賭けで（相関0.90）、独立の確認ではありません。
(4) テーマ Value の C7 は t=3.00001 で、n≥29 なら2.99に落ちます。B2 の訓練期間は QMJ が3〜7銘柄の時期に依存しています。
主張の一覧に無い E4_value_quality_mom（割安＋質＋勢い）は S のまま確認しました（保有 +1.6% t3.6、2007-2021年 t2.75、他国19/19）。E4_value_mom は A に、E4_def_value・上限つき配当は B に下げました。"""


if __name__ == '__main__':
    r = main()
    for k, v in r['candidates'].items():
        c, f, t, h = v['claimed'], v['full'], v['train'], v['hold']
        print(f"{k:28s} claim tr {c['train_ex']}/{c['train_t']} ho {c['hold_ex']}/{c['hold_t']} full {c['full_ex']}/{c['full_t']} | mine tr {t['ex']}/{t['t']} y{t['years']} ho {h['ex']}/{h['t']} cg{h['cagr_diff']} full {f['ex']}/{f['t']} r20 {v['roll20'] and v['roll20']['win_rate']}")
