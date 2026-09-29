#!/usr/bin/env python3
"""night/mw_oap_signals_verify.py — 角度 oap_signals の『反証の検証』（読むだけ・門・採点・配分には不使用）

研究側（night/mw_oap_signals.py → out/mw_oap_signals.json）が S・A と付けた7本と、B の中で保有期間の超過が大きい2本
（＋主の族で唯一の B の REV6）を、研究側のコードを一切使わずに作り直して反証を試みる。

独立に書いたもの（研究側と共有しない）
- OAP の zip（PredictorAltPorts_*）を自前で読む（研究側の pickle は読まない）
- French 3因子の CSV を自前で読む（Mkt = Mkt-RF + RF）
- 超過の平均・Newey-West t・幾何の年率差・転がる20年窓・費用控除・CAPM のα・税の試算は全部この中で書いた
- 回転率は仮定を置かず、各予言因子の定義（窓の長さ・組み直しの間隔・分位）どおりの合成データで測る（下限の見積もり）
共有したもの: mw_common の取得（get・jkp_rows・french_tables・yahoo）だけ。

使い方: python3 night/mw_oap_signals_verify.py   → out/mw_oap_signals_verify.json
"""
import sys, os, io, csv, json, math, zipfile, random, collections, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402  取得だけに使う

BASE = M.BASE
OUT = os.path.join(BASE, 'out', 'mw_oap_signals_verify.json')
RES = os.path.join(BASE, 'out', 'mw_oap_signals.json')
DRIVE = 'https://drive.usercontent.google.com/download?id={}&export=download&confirm=t'
OAPF = {'D': ('1_1WWZqilrt1gleeyAFwjv5aobd0QRbS3', 'oap202510_PredictorAltPorts_DecilesVW.zip'),
        'Q': ('1ef905SSlCDyh1KU9W1tJs5sfBFz0HPUt', 'oap202510_PredictorAltPorts_QuintilesVW.zip'),
        'V': ('1KZE3FgBxFPaNOyxoRw63ubZHOlkR9kZW', 'oap202510_PredictorAltPorts_LiqScreen_VWforce.zip'),
        'L': ('1Q4YatQ3soRU_V7VeACwUn2bnCnmhDUI2', 'oap202510_PredictorAltPorts_LiqScreen_ME_gt_NYSE20pct.zip')}
END = 202412
NMIN = 20
TAX = 0.20315
TSLA_CACHE = {}
TR_END, H0 = 200612, 200701

# 検証する候補（研究側の id → 自前の作り方）
CANDS = {
    'SQ:MomOffSeason06YrPlus': ('MomOffSeason06YrPlus', 'Q', '05', 'S'),
    'S:ShareIss1Y': ('ShareIss1Y', 'D', '10', 'S'),
    'S:ShareIss5Y': ('ShareIss5Y', 'D', '10', 'S'),
    'S:Mom6m': ('Mom6m', 'D', '10', 'A'),
    'S:Mom12mOffSeason': ('Mom12mOffSeason', 'D', '10', 'A'),
    'S:Mom12m': ('Mom12m', 'D', '10', 'A'),
    'SQ:IntMom': ('IntMom', 'Q', '05', 'A'),
    'S:Mom6mJunk': ('Mom6mJunk', 'D', '10', 'B'),
    'SQ:ProbInformedTrading': ('ProbInformedTrading', 'Q', '05', 'B'),
    'P:REV6': ('REV6', 'D', '10', 'B'),
}
SIGS = sorted({v[0] for v in CANDS.values()} | {'Size'})
# 研究側が仮定した片道回転率（年）
ASSUMED_TURN = {'MomOffSeason06YrPlus': 2.0, 'ShareIss1Y': 0.5, 'ShareIss5Y': 0.5, 'Mom6m': 1.0, 'Mom12mOffSeason': 2.0,
                'Mom12m': 1.0, 'IntMom': 2.0, 'Mom6mJunk': 2.0, 'ProbInformedTrading': 2.0, 'REV6': 2.0}
# 独立の作り方（JKP の良い側の三分位・'vw'・超過 → French RF を足す）
JKP_CP = {'MomOffSeason06YrPlus': ('seas_6_10na', -1), 'ShareIss1Y': ('chcsho_12m', -1), 'ShareIss5Y': ('eqnpo_12m', 1),
          'Mom6m': ('ret_6_1', 1), 'Mom12mOffSeason': ('seas_1_1na', 1), 'Mom12m': ('ret_12_1', 1), 'IntMom': ('ret_12_7', 1),
          'Mom6mJunk': ('ret_6_1', 1)}


# ───────────────────────── 読み込み（自前） ─────────────────────────
def load_oap():
    out = {}
    for k, (fid, fname) in OAPF.items():
        b = M.get(DRIVE.format(fid), name=fname, max_age_days=3650)
        z = zipfile.ZipFile(io.BytesIO(b))
        fh = io.TextIOWrapper(z.open(z.namelist()[0]), encoding='utf-8')
        rd = csv.reader(fh)
        head = next(rd)
        ix = {h: i for i, h in enumerate(head)}
        d = collections.defaultdict(dict)
        for r in rd:
            s = r[ix['signalname']]
            if s not in SIGS:
                continue
            ret = r[ix['ret']]
            if ret in ('', 'NA'):
                continue
            dt = r[ix['date']]
            ym = int(dt[:4]) * 100 + int(dt[5:7])
            nl = r[ix['Nlong']]
            d[(s, r[ix['port']])][ym] = (float(ret) / 100.0, None if nl in ('', 'NA') else int(float(nl)))
        out[k] = dict(d)
    return out


def leg(O, f, s, p, nmin=NMIN, end=END):
    d = O[f].get((s, p))
    if not d:
        return {}
    return {m: r for m, (r, n) in d.items() if m <= end and (n is None or n >= nmin)}


def ports_of(O, f, s):
    return sorted(p for (ss, p) in O[f] if ss == s and p != 'LS')


def ff3():
    b = M.get('https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip',
              name='fr_F-F_Research_Data_Factors.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    txt = z.read(z.namelist()[0]).decode('latin-1').splitlines()
    mkt, rf, started = {}, {}, False
    for line in txt:
        c = [x.strip() for x in line.split(',')]
        if len(c) >= 5 and c[1] == 'Mkt-RF':
            if started:
                break
            started = True
            continue
        if started:
            if len(c) >= 5 and c[0].isdigit() and len(c[0]) == 6:
                m = int(c[0]); mkt[m] = (float(c[1]) + float(c[4])) / 100; rf[m] = float(c[4]) / 100
            elif c[0] and not c[0].isdigit():
                break
    return mkt, rf


# ───────────────────────── 統計（自前） ─────────────────────────
def mean(x):
    return math.fsum(x) / len(x)


def nwt(x, L=12):
    n = len(x)
    if n < 24:
        return None
    m = mean(x)
    e = [v - m for v in x]
    s = math.fsum(v * v for v in e) / n
    for l in range(1, min(L, n - 1) + 1):
        s += 2 * (1 - l / (L + 1)) * math.fsum(e[i] * e[i - l] for i in range(l, n)) / n
    return m / math.sqrt(s / n) if s > 0 else None


def geo(x):
    return math.exp(math.fsum(math.log1p(v) for v in x) * 12 / len(x)) - 1


def stats(s, b, a=None, z=None, L=12):
    ks = sorted(k for k in s if k in b and (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 24:
        return None
    ex = [s[k] - b[k] for k in ks]
    t = nwt(ex, L)
    sv, bv = [s[k] for k in ks], [b[k] for k in ks]
    mb, ms = mean(bv), mean(sv)
    beta = math.fsum((x - ms) * (y - mb) for x, y in zip(sv, bv)) / math.fsum((y - mb) ** 2 for y in bv)
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex': round(mean(ex) * 1200, 2), 't': round(t, 3) if t is not None else None,
            'cagr_s': round(geo(sv) * 100, 2), 'cagr_b': round(geo(bv) * 100, 2), 'cagr_diff': round((geo(sv) - geo(bv)) * 100, 2),
            'beta': round(beta, 2)}


def capm(s, b, rf, a=None, z=None):
    ks = sorted(k for k in s if k in b and k in rf and (a is None or k >= a) and (z is None or k <= z))
    ys = [s[k] - rf[k] for k in ks]; xs = [b[k] - rf[k] for k in ks]
    mx, my = mean(xs), mean(ys)
    beta = math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.fsum((x - mx) ** 2 for x in xs)
    al = my - beta * mx
    res = [y - al - beta * x for x, y in zip(xs, ys)]
    t = nwt([al + e for e in res])
    return {'beta': round(beta, 2), 'alpha': round(al * 1200, 2), 't_approx': round(t, 2) if t else None}


def roll(s, b, years=20):
    ks = set(s) & set(b)
    y0 = min(ks) // 100
    out = []
    for y in range(y0, 2100):
        w = []
        for i in range(years * 12):
            yy, mm = y + (6 + i) // 12, (6 + i) % 12 + 1
            w.append(yy * 100 + mm)
        if w[-1] > max(ks):
            break
        if not all(m in ks for m in w):
            continue
        out.append((y, (geo([s[m] for m in w]) - geo([b[m] for m in w])) * 100))
    if not out:
        return None
    v = sorted(x for _, x in out)
    return {'windows': len(out), 'win_rate': round(sum(1 for x in v if x > 0) / len(v), 3), 'median': round(v[len(v) // 2], 2),
            'worst': [min(out, key=lambda x: x[1])[0], round(min(v), 2)]}


def cost(s, turn, unit):
    c = turn * unit / 12
    return {k: v - c for k, v in s.items()}


def cal_years(s, b, a, z):
    ys = collections.defaultdict(lambda: [1.0, 1.0])
    for k in s:
        if k in b and a <= k <= z:
            ys[k // 100][0] *= 1 + s[k]; ys[k // 100][1] *= 1 + b[k]
    return {y: (v[0] - 1, v[1] - 1) for y, v in ys.items()}


def drop_years(s, b, years):
    return {k: v for k, v in s.items() if k // 100 not in years}, {k: v for k, v in b.items() if k // 100 not in years}


def after_tax(s, b, turn, a=H0, z=END):
    """日本の課税口座（20.315%）の試算。戦略は毎年、含み益の min(1, 回転率) を実現（損は繰越・期限なし＝戦略に甘い）。
    相手（指数を持ち続ける）は最後に一度だけ課税。戻り値は税引後の年率の差（%）"""
    f = min(1.0, turn)
    ys = cal_years(s, b, a, z)
    W, B, Lc = 1.0, 1.0, 0.0
    Wb = 1.0
    for y in sorted(ys):
        rs, rb = ys[y]
        W *= 1 + rs; Wb *= 1 + rb
        real = f * (W - B)
        if real > 0:
            tx = TAX * max(0.0, real - Lc); Lc = max(0.0, Lc - real)
            W -= tx; B += real - tx
        else:
            Lc += -real; B += real
    tx = TAX * max(0.0, (W - B) - Lc)
    W -= tx
    Wb -= TAX * max(0.0, Wb - 1)
    n = len(ys)
    return {'years': n, 'cagr_after_tax_s': round((W ** (1 / n) - 1) * 100, 2), 'cagr_after_tax_b': round((Wb ** (1 / n) - 1) * 100, 2),
            'diff': round(((W ** (1 / n)) - (Wb ** (1 / n))) * 100, 2), 'realize_fraction_per_year': f}


# ───────────────────────── 回転率（合成データで測る） ─────────────────────────
def sim_turnover(kind, q, period, seed=1, N=1500, years=30, rho=0.3):
    """予言因子の定義どおりの窓・組み直しの間隔・分位で、時価加重の端の片道回転率（年）を測る。
    銘柄のリターンは独立（予言力なし）・ぶれは小型ほど大きい・上場廃止と新規上場なし＝入れ替えは『窓が動くことによる分』だけ＝下限"""
    rnd = random.Random(seed)
    T = years * 12 + 130
    lz = [rnd.gauss(0, 1.7) for _ in range(N)]
    sig = [math.exp(math.log(0.10) - 0.18 * z + rnd.gauss(0, 0.3)) for z in lz]
    be = [max(0.2, rnd.gauss(1.0, 0.3)) for _ in range(N)]
    R = []
    for t in range(T):
        m = rnd.gauss(0.007, 0.045)
        R.append([max(-0.95, be[i] * m + sig[i] * rnd.gauss(0, 1)) for i in range(N)])
    ME = [math.exp(z) for z in lz]
    MEs = []
    for t in range(T):
        MEs.append(ME[:])
        ME = [ME[i] * (1 + R[t][i]) for i in range(N)]
    g = [rnd.gauss(0, 1) for _ in range(N)]  # 株数の変化（年）の潜在の値
    G = {}
    for yy in range(T // 12 + 2):
        g = [rho * g[i] + math.sqrt(1 - rho * rho) * rnd.gauss(0, 1) for i in range(N)]
        G[yy] = g[:]

    def signal(t):
        if kind == 'mom':  # 窓 (lo, hi) のラグの積
            lo, hi = q['win']
            return [math.fsum(math.log1p(R[t - l][i]) for l in range(lo, hi + 1)) for i in range(N)]
        if kind == 'offseason':  # ラグ lo..hi の平均・12の倍数のラグを除く
            lo, hi = q['win']
            ls = [l for l in range(lo, hi + 1) if l % 12 != 0]
            return [math.fsum(R[t - l][i] for l in ls) / len(ls) for i in range(N)]
        if kind == 'iss':  # 年の株数の変化（窓 k 年の和）
            y = t // 12
            return [math.fsum(G[y - j][i] for j in range(q['k'])) for i in range(N)]
        raise ValueError(kind)

    frac = q['frac']
    start = 125
    w, tot, cnt_months = {}, 0.0, 0
    for t in range(start, T):
        if w:  # 保有の値動きで重みが流れる
            v = {i: w[i] * (1 + R[t - 1][i]) for i in w}
            sm = math.fsum(v.values()); w = {i: x / sm for i, x in v.items()}
        if (t - start) % period == 0:
            sg = signal(t)
            k = max(1, int(N * frac))
            sel = sorted(range(N), key=lambda i: -sg[i])[:k]
            sm = math.fsum(MEs[t][i] for i in sel)
            nw = {i: MEs[t][i] / sm for i in sel}
            if w:
                ks = set(w) | set(nw)
                tot += math.fsum(abs(nw.get(i, 0) - w.get(i, 0)) for i in ks) / 2
                cnt_months += 0
            w = nw
    months = T - start
    return round(tot / (months / 12), 2)


TURN_SPECS = {  # 定義は OAP の SignalDoc（窓・Portfolio Period）どおり。月のラグはリターンの月から数える
    'Mom6m': ('mom', {'win': (2, 6), 'frac': 0.1}, 3),
    'Mom12m': ('mom', {'win': (2, 12), 'frac': 0.1}, 3),
    'IntMom': ('mom', {'win': (7, 12), 'frac': 0.2}, 1),
    'Mom12mOffSeason': ('offseason', {'win': (2, 11), 'frac': 0.1}, 1),
    'MomOffSeason06YrPlus': ('offseason', {'win': (61, 120), 'frac': 0.2}, 1),
    'Mom6mJunk': ('mom', {'win': (2, 6), 'frac': 0.1}, 1),
    'ShareIss1Y': ('iss', {'k': 1, 'frac': 0.1}, 12),
    'ShareIss5Y': ('iss', {'k': 5, 'frac': 0.1}, 12),
}


# ───────────────────────── 本体 ─────────────────────────
def main():
    res = json.load(open(RES))
    T = {x['id']: x for x in res['tested']}
    O = load_oap()
    mkt, rf = ff3()
    out = {'angle': 'oap_signals', 'verifier': 'adversarial verifier（独立の実装）', 'generated': datetime.date.today().isoformat(),
           'independent_parts': ['OAP zip の自前の読み込み（研究側の pickle は不使用）', 'French 3因子 CSV の自前の読み込み',
                                 '超過・NW t・CAGR 差・20年窓・費用・CAPM α・税の試算', '回転率を合成データで定義どおりに測定（研究側は仮定）'],
           'shared_parts': ['mw_common.get / jkp_rows / french_tables / yahoo（取得だけ）']}

    # ── 健全性: 市場・日付の揃い ──
    san = {'mkt_cagr_192607_202412': round(geo([mkt[k] for k in sorted(mkt) if k <= END]) * 100, 2),
           'mkt_cagr_2007_2024': round(geo([mkt[k] for k in sorted(mkt) if H0 <= k <= END]) * 100, 2)}
    sz = leg(O, 'D', 'Size', '01', nmin=0)
    ks = sorted(k for k in sz if k in mkt)
    for lag in (-1, 0, 1):
        pairs = [(sz[k], mkt.get(M_shift(k, lag))) for k in ks if M_shift(k, lag) in mkt]
        san[f'corr_size01_mkt_lag{lag}'] = round(M.corr([a for a, _ in pairs], [b for _, b in pairs]), 4)
    mo = M.french_series('10_Portfolios_Prior_12_2', 'Value Weight')['Hi PRIOR']
    m12 = leg(O, 'D', 'Mom12m', '10')
    for lag in (-1, 0, 1):
        pairs = [(m12[k], mo.get(M_shift(k, lag))) for k in sorted(m12) if M_shift(k, lag) in mo]
        san[f'corr_mom12m_d10_frenchHiPRIOR_lag{lag}'] = round(M.corr([a for a, _ in pairs], [b for _, b in pairs]), 4)
    out['sanity'] = san

    # ── 研究側の数字の再現と反証の材料 ──
    JKPD = {}
    ni = M.french_series('Portfolios_Formed_on_NI', 'Value Weight')
    cands = {}
    for cid, (s, f, p, claimed) in CANDS.items():
        x = T[cid]; e = x['eval']
        L = leg(O, f, s, p)
        c = {'claimed_grade': claimed, 'signal': s, 'portfolio': f'{f}:{p}'}
        c['full'] = stats(L, mkt); c['train'] = stats(L, mkt, z=TR_END); c['hold'] = stats(L, mkt, a=H0)
        c['recent_2013_07'] = stats(L, mkt, a=201307)
        c['hold_t_lag6_lag24'] = [round(nwt([L[k] - mkt[k] for k in sorted(L) if k in mkt and k >= H0], 6), 3),
                                  round(nwt([L[k] - mkt[k] for k in sorted(L) if k in mkt and k >= H0], 24), 3)] if c['hold'] else None
        c['roll20'] = roll(L, mkt)
        c['research_numbers'] = {'full': [e['full']['ex_ann'], e['full']['t']], 'train': [e['train']['ex_ann'], e['train']['t']],
                                 'hold': [e['hold']['ex_ann'], e['hold']['t'], e['hold']['cagr_diff']],
                                 'net': [e['cost_hold']['ex_ann'], e['cost_hold']['cagr_diff']], 'roll20': e['roll20'] and e['roll20']['win_rate']}
        rep = c['hold'] and abs(c['hold']['ex'] - e['hold']['ex_ann']) < 0.05 and abs(c['train']['ex'] - e['train']['ex_ann']) < 0.05 \
            and abs(c['full']['t'] - e['full']['t']) < 0.02
        c['reproduced'] = bool(rep)
        # 費用: 研究側の仮定・合成データの回転率・損益分岐
        ta = ASSUMED_TURN[s]
        c['turnover_assumed'] = ta
        if s in TURN_SPECS:
            kind, q, per = TURN_SPECS[s]
            sims = [sim_turnover(kind, q, per, seed=sd) for sd in (1, 2)]
            if s in ('ShareIss1Y', 'ShareIss5Y'):
                sims += [sim_turnover(kind, q, per, seed=3, rho=0.0), sim_turnover(kind, q, per, seed=4, rho=0.6)]
            c['turnover_sim'] = sims
            tsim = round(mean(sims[:2]), 2)
        else:
            c['turnover_sim'] = None
            tsim = ta
        c['turnover_used_for_realistic_cost'] = tsim
        if c['hold']:
            gross = c['hold']['cagr_diff']
            c['breakeven_turnover_at_0.30pct'] = round(gross / 0.30, 1)
            for tag, tt, u in (('net_assumed_0.30', ta, 0.003), ('net_sim_0.30', tsim, 0.003), ('net_sim_0.50', tsim, 0.005), ('net_sim_0.10', tsim, 0.001)):
                c[tag] = stats(cost(L, tt, u), mkt, a=H0)
            c['after_tax_jp_hold'] = after_tax(cost(L, tsim, 0.003), mkt, tsim)
            c['sub_2007_2015'] = stats(L, mkt, a=H0, z=201512)
            c['sub_2016_2024'] = stats(L, mkt, a=201601, z=END)
            c['sub_2007_2012'] = stats(L, mkt, a=H0, z=201212)
            yrs = cal_years(L, mkt, H0, END)
            best2 = sorted(yrs, key=lambda y: -(yrs[y][0] - yrs[y][1]))[:2]
            ds, db = drop_years(L, mkt, set(best2))
            c['hold_drop_best2_years'] = {'dropped': best2, 'stats': stats(ds, db, a=H0)}
            c['capm_hold'] = capm(L, mkt, rf, a=H0)
            # 近い作り方（十分位9・五分位4・原論文の分位の時価加重・大型株〔NYSE20%点超〕の原論文の重み）
            nb = {}
            pd, pq, pv, pl = ports_of(O, 'D', s), ports_of(O, 'Q', s), ports_of(O, 'V', s), ports_of(O, 'L', s)
            for tag, ff, pp in (('D10', 'D', pd[-1] if pd else None), ('D09', 'D', pd[-2] if len(pd) > 1 else None),
                                ('Q05', 'Q', pq[-1] if pq else None), ('Q04', 'Q', pq[-2] if len(pq) > 1 else None),
                                ('VWforce_top', 'V', pv[-1] if pv else None), ('LargeCap_top', 'L', pl[-1] if pl else None)):
                if not pp:
                    continue
                LL = leg(O, ff, s, pp)
                st = stats(LL, mkt, a=H0)
                nb[tag] = {'port': pp, 'train': stats(LL, mkt, z=TR_END), 'hold': st,
                           'net_sim': stats(cost(LL, tsim, 0.003), mkt, a=H0) if st else None}
            c['neighbors'] = nb
        # NW のラグを変えた t（6・12・24）: 訓練・保有・全期間
        def tl(a=None, z=None):
            ex = [L[k] - mkt[k] for k in sorted(L) if k in mkt and (a is None or k >= a) and (z is None or k <= z)]
            return [round(nwt(ex, lg), 3) if len(ex) >= 24 else None for lg in (6, 12, 24)]
        c['t_by_nw_lag_6_12_24'] = {'train': tl(z=TR_END), 'hold': tl(a=H0), 'full': tl()}
        # 分位ごとの保有期間の超過（単調か）
        mono = {}
        for ff in ('D', 'Q'):
            ps = ports_of(O, ff, s)
            if not ps:
                continue
            row = {}
            for pp in ps:
                st = stats(leg(O, ff, s, pp), mkt, a=H0)
                row[pp] = st['ex'] if st else None
            vals = [(i, v) for i, (pp, v) in enumerate(sorted(row.items())) if v is not None]
            if len(vals) >= 5:
                rk = lambda xs: [sorted(xs).index(x) for x in xs]
                mono[ff] = {'hold_ex_by_port': row, 'spearman_port_vs_hold_ex': round(M.corr(rk([i for i, _ in vals]), rk([v for _, v in vals])), 3)}
        c['hold_by_port'] = mono
        # 2020 年だけ・Tesla への当てはめの重み（勢いの端が一社に寄るか）
        try:
            ts = TSLA_CACHE.setdefault('t', M.yahoo('TSLA'))
            ks = [k for k in sorted(L) if 202001 <= k <= 202012 and k in ts and k in mkt]
            a_ = [L[k] - mkt[k] for k in ks]; b_ = [ts[k] - mkt[k] for k in ks]
            mb_ = mean(b_); ma_ = mean(a_)
            c['tsla_2020'] = {'implied_weight': round(math.fsum((x - mb_) * (y - ma_) for x, y in zip(b_, a_)) / math.fsum((x - mb_) ** 2 for x in b_), 2),
                              'corr': round(M.corr(a_, b_), 2), 'port_excess_2020_pct': round((math.prod(1 + L[k] for k in ks) - math.prod(1 + mkt[k] for k in ks)) * 100, 1),
                              'hold_without_2020': stats(*drop_years(L, mkt, {2020}), a=H0)}
        except Exception as ex:  # noqa
            c['tsla_2020'] = {'error': str(ex)[:200]}
        # C5 を自前で（JKP の良い側の三分位 vs 同じ地域の vw 市場・全期間 1990〜 と 保有 2007〜）
        if s in JKP_CP:
            j, dirn = JKP_CP[s]
            pf = '3.0' if dirn == 1 else '1.0'
            c5 = {}
            for reg in ('developed', 'emerging', 'jpn'):
                if reg not in JKPD:
                    JKPD[reg] = M.jkp_rows(reg, 'all_factors', 'portfolios', 'vw')
                    JKPD['mkt_' + reg] = M.jkp_mkt(reg, 'vw')
                g = {M._ym(r['date']): float(r['ret']) for r in JKPD[reg] if r['name'] == j and r['pf'] == pf and r['ret'] not in ('', 'NA', 'na')
                     and (r['n'] in ('', 'NA', 'na') or float(r['n']) >= NMIN)}
                mm = JKPD['mkt_' + reg]
                f_ = stats(g, mm, a=199001); h_ = stats(g, mm, a=H0)
                c5[reg] = {'full_1990': f_ and [f_['ex'], f_['t']], 'hold_2007': h_ and [h_['ex'], h_['t']]}
            c5['positive_full_of_2'] = sum(1 for r in ('developed', 'emerging') if c5[r]['full_1990'] and c5[r]['full_1990'][0] > 0)
            c5['positive_hold_of_2'] = sum(1 for r in ('developed', 'emerging') if c5[r]['hold_2007'] and c5[r]['hold_2007'][0] > 0)
            c['c5_own'] = c5
        # 独立の作り方
        ind = {}
        if s in JKP_CP:
            j, dirn = JKP_CP[s]
            if 'usa' not in JKPD:
                JKPD['usa'] = M.jkp_rows('usa', 'all_factors', 'portfolios', 'vw')
            pf = '3.0' if dirn == 1 else '1.0'
            g = {M._ym(r['date']): float(r['ret']) for r in JKPD['usa'] if r['name'] == j and r['pf'] == pf and r['ret'] not in ('', 'NA', 'na')}
            tot = {k: v + rf[k] for k, v in g.items() if k in rf}
            ind[f'JKP_usa_{j}_tercile{pf}_vw'] = {'hold_2007_2025': stats(tot, mkt, a=H0), 'hold_2007_2024': stats(tot, mkt, a=H0, z=END),
                                                  'train': stats(tot, mkt, z=TR_END), 'y2025': stats(tot, mkt, a=202401, z=202512)}
        if s in ('ShareIss1Y', 'ShareIss5Y'):
            f0 = ni['< 0']
            ind['French_NI_lt0_vw'] = {'hold_2007_2026_08': stats(f0, mkt, a=H0), 'hold_2007_2024': stats(f0, mkt, a=H0, z=END),
                                       'train_1963_2006': stats(f0, mkt, z=TR_END)}
        if s == 'Mom12m':
            ind['French_Prior_12_2_HiPRIOR_vw'] = {'hold_2007_2026_08': stats(mo, mkt, a=H0), 'hold_2007_2024': stats(mo, mkt, a=H0, z=END),
                                                   'train': stats(mo, mkt, z=TR_END)}
        c['independent_constructions'] = ind
        # C5（研究側の地域の答え合わせ）を保有期間でも
        c['research_repl_detail_hold'] = {r: ((v or {}).get('hold') or {}).get('ex_ann') for r, v in (x.get('repl_detail') or {}).items()} if x.get('repl_detail') else None
        cands[cid] = c
        print(cid, 'reproduced', c['reproduced'], 'hold', c['hold'] and (c['hold']['ex'], c['hold']['t'], c['hold']['cagr_diff']),
              'turn', ta, '->', tsim, 'net_sim', c.get('net_sim_0.30') and (c['net_sim_0.30']['ex'], c['net_sim_0.30']['cagr_diff']), flush=True)
    out['candidates'] = cands

    # ── Mom6mJunk: 一社（Tesla 等）への依存 ──
    try:
        junk = leg(O, 'D', 'Mom6mJunk', '10')
        act = {k: junk[k] - mkt[k] for k in junk if k in mkt}
        tk = {}
        for t in ('TSLA', 'NFLX', 'AMD'):
            y = M.yahoo(t)
            ta_ = {k: y[k] - mkt[k] for k in y if k in mkt}
            ks = sorted(k for k in act if k in ta_ and 201101 <= k <= END)
            tk[t] = {'corr_active_2011_2024': round(M.corr([act[k] for k in ks], [ta_[k] for k in ks]), 3), 'months': len(ks)}
        ys = cal_years(junk, mkt, H0, END)
        tk['calendar_year_excess_hold'] = {y: round((a - b) * 100, 1) for y, (a, b) in sorted(ys.items())}
        tk['hold_without_2020_2021'] = stats(*drop_years(junk, mkt, {2020, 2021}), a=H0)
        tk['hold_without_2020'] = stats(*drop_years(junk, mkt, {2020}), a=H0)
        ts = M.yahoo('TSLA')
        wy = {}
        for yy in range(2016, 2025):
            ks = [k for k in sorted(junk) if k // 100 == yy and k in ts and k in mkt]
            a_ = [junk[k] - mkt[k] for k in ks]; b_ = [ts[k] - mkt[k] for k in ks]
            mb_, ma_ = mean(b_), mean(a_)
            wy[yy] = {'implied_weight': round(math.fsum((x - mb_) * (y - ma_) for x, y in zip(b_, a_)) / math.fsum((x - mb_) ** 2 for x in b_), 2),
                      'corr': round(M.corr(a_, b_), 2)}
        tk['tsla_implied_weight_by_year'] = wy
        nl = collections.defaultdict(list)
        for m, (r, n) in O['D'][('Mom6mJunk', '10')].items():
            if n is not None:
                nl[m // 100].append(n)
        tk['nlong_d10_median_by_year'] = {y: sorted(v)[len(v) // 2] for y, v in sorted(nl.items()) if y >= 2010}
        tk['note'] = ('S&P の格付けは Compustat の格付けファイルが 2017-02 で終わる（WRDS の周知の事実）。Nlong は 2016 の約75から 2020 以降約50へ減った。'
                      'Tesla は S&P で 2022-10 に BBB（投資適格）へ上がった。2023 年の当てはめの重みが残るのは、格付けが古いまま使われている疑い（確定はできない）')
        out['mom6mjunk_concentration'] = tk
    except Exception as ex:  # noqa
        out['mom6mjunk_concentration'] = {'error': str(ex)[:300]}

    # ── 多重検定 ──
    tested = res['tested']
    nt = len(tested)
    summ = json.load(open(os.path.join(BASE, 'out', 'mw_summary.json')))
    out['multiple_testing'] = {
        'angle_tested': nt,
        'families': {f: sum(1 for x in tested if x.get('family') == f) for f in sorted({x.get('family') for x in tested})},
        'program_tests_total': summ.get('program_tests_total'), 'program_bonferroni_t': summ.get('bonferroni_t_program_wide'),
        'angle_bonferroni_t_two_sided_0.05': round(inv_norm(1 - 0.025 / nt), 2),
        'n_hold_t_ge_angle_bonf': sum(1 for x in tested if ((x.get('eval') or {}).get('hold') or {}).get('t') and x['eval']['hold']['t'] >= inv_norm(1 - 0.025 / nt)),
        'n_hold_t_ge_1.65_of_evaluable': [sum(1 for x in tested if ((x.get('eval') or {}).get('hold') or {}).get('t', -9) is not None and ((x.get('eval') or {}).get('hold') or {}).get('t', -9) >= 1.65),
                                          sum(1 for x in tested if (x.get('eval') or {}).get('hold'))],
        'n_hold_t_le_-1.65': sum(1 for x in tested if (((x.get('eval') or {}).get('hold') or {}).get('t') or 0) <= -1.65),
    }
    # ── 自前の格付け（out/mw_prereg.json の線を自分で書いた式で当てる） ──
    def grade_own(c, net_key, tsel, c5):
        tr, ho, fu = c['train'], c['hold'], c['full']
        t_tr = tsel(c['t_by_nw_lag_6_12_24']['train']); t_ho = tsel(c['t_by_nw_lag_6_12_24']['hold']); t_fu = tsel(c['t_by_nw_lag_6_12_24']['full'])
        nt_ = c.get(net_key)
        cr = {'C1': bool(tr and tr['ex'] > 0 and (t_tr or 0) >= 2.0), 'C2': bool(ho and ho['ex'] > 0 and ho['cagr_diff'] > 0),
              'C3': bool(ho and (t_ho or 0) >= 1.65), 'C4': bool(c['roll20'] and c['roll20']['win_rate'] >= 0.8), 'C5': c5,
              'C6': bool(nt_ and nt_['ex'] > 0 and nt_['cagr_diff'] > 0), 'C7': bool((t_fu or 0) >= 3.0)}
        base = cr['C1'] and cr['C2'] and cr['C6']
        if base and cr['C3'] and cr['C4'] and cr['C7'] and cr['C5'] in (None, True):
            g = 'S'
        elif base and cr['C4'] and cr['C7'] and (cr['C3'] or cr['C5'] is True):
            g = 'A'
        elif base:
            g = 'B'
        else:
            g = 'C'
        return g, cr
    for cid, c in cands.items():
        x = T[cid]
        c5 = None
        if x.get('repl'):  # 研究側の事前登録の規則で相手が決まったものだけ（相手なし＝N/A）
            c5 = (c.get('c5_own') or {}).get('positive_full_of_2', 0) >= 2
        c['grade_own'] = {
            'as_registered_lag12_assumed_turnover': grade_own(c, 'net_assumed_0.30', lambda v: v[1], c5),
            'lag12_simulated_turnover': grade_own(c, 'net_sim_0.30', lambda v: v[1], c5),
            'worst_of_lag6_12_24_simulated_turnover': grade_own(c, 'net_sim_0.30', lambda v: min(u for u in v if u is not None) if any(u is not None for u in v) else None, c5)}
    out['verdicts'] = build_verdicts(cands, out)
    out['selection'] = ('研究側の S・A は7本（S: SQ:MomOffSeason06YrPlus・S:ShareIss1Y・S:ShareIss5Y／A: S:Mom6m・S:Mom12mOffSeason・S:Mom12m・SQ:IntMom）＝8本以下なので全部。'
                        'B の保有期間の超過の上位2本（S:Mom6mJunk +9.73・SQ:ProbInformedTrading +8.20）。加えて主の族で唯一の B（P:REV6）')
    out['benchmark_note'] = ('相手は French の Mkt（Mkt-RF＋RF・上限なしの時価加重・CRSP 全上場）＝全体の事前登録どおりで、この投資家にとっての米国市場そのもの。'
                             'OAP の ret は総リターン（Size 第1十分位と Mkt の同月の相関 0.993・前後1か月は 0.07〜0.08＝日付の揃いも確認）。上場廃止のリターン込み（生き残りの偏りなし）')
    out['conclusion_ja'] = CONCLUSION
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('wrote', OUT)


def _s(st, k='ex'):
    return None if not st else st.get(k)


def _st(st):
    return '—' if not st else f"{st['ex']:+.2f}%/年 t{st['t']:.2f}（幾何差 {st['cagr_diff']:+.2f}）"


def keynum(c):
    lg = c['t_by_nw_lag_6_12_24']
    return (f"再現: 全期間 {_st(c['full'])}／訓練 {_st(c['train'])}／保有 {_st(c['hold'])}／"
            f"保有 t の NW ラグ 6・12・24 = {lg['hold']}／20年窓 {c['roll20'] and c['roll20']['win_rate']}／"
            f"費用後（研究側の回転率 {c['turnover_assumed']}/年）{_st(c.get('net_assumed_0.30'))}／"
            f"費用後（定義どおりの回転率 {c['turnover_used_for_realistic_cost']}/年・0.30%）{_st(c.get('net_sim_0.30'))}")


# 判定（数字を見た後に書いた。数字は下の式で c から引く＝文と数字がずれない）
VERDICT_RULES = {
    'SQ:MomOffSeason06YrPlus': ('downgraded to A', 'A'),
    'S:ShareIss1Y': ('downgraded to A', 'A'),
    'S:ShareIss5Y': ('downgraded to B', 'B'),
    'S:Mom6m': ('downgraded to B', 'B'),
    'S:Mom12mOffSeason': ('downgraded to B', 'B'),
    'S:Mom12m': ('downgraded to B', 'B'),
    'SQ:IntMom': ('downgraded to C', 'C'),
    'S:Mom6mJunk': ('downgraded to C', 'C'),
    'SQ:ProbInformedTrading': ('refuted', 'C'),
    'P:REV6': ('confirmed', 'B'),
}


def build_verdicts(cands, out):
    mt = out['multiple_testing']
    mtxt = (f"多重検定: この角度で {mt['angle_tested']} 本（保有期間の t≥1.65 は {mt['n_hold_t_ge_1.65_of_evaluable'][0]}/{mt['n_hold_t_ge_1.65_of_evaluable'][1]}・"
            f"t≤−1.65 は {mt['n_hold_t_le_-1.65']}＝勝ちの尾は偶然の数を超えない）。角度の Bonferroni t {mt['angle_bonferroni_t_two_sided_0.05']}・"
            f"プログラム全体 {mt['program_tests_total']} 本の線 t {mt['program_bonferroni_t']} を保有期間で越えるものは0")
    V = []
    for cid, c in cands.items():
        v, g = VERDICT_RULES[cid]
        nb = c.get('neighbors') or {}
        nbt = '・'.join(f"{k}({d['port']}) {_st(d['hold'])}" for k, d in nb.items() if d.get('hold'))
        ind = c.get('independent_constructions') or {}
        indt = '・'.join(f"{k} " + _st(d.get('hold_2007_2024')) for k, d in ind.items())
        dr = c.get('hold_drop_best2_years') or {}
        c5 = c.get('c5_own')
        c5t = (f"JKP の同じ主題（三分位）の米国外: 先進国 全期間 {c5['developed']['full_1990']}・保有 {c5['developed']['hold_2007']}／新興国 全期間 {c5['emerging']['full_1990']}・保有 {c5['emerging']['hold_2007']}"
               if c5 else 'C5 は研究側の事前登録の規則で相手なし（N/A）')
        mono = c.get('hold_by_port') or {}
        monot = '／'.join(f"{ff} の分位ごとの保有の超過 {d['hold_ex_by_port']}（順位相関 {d['spearman_port_vs_hold_ex']}）" for ff, d in mono.items())
        iss = [
            f"独立の再計算で研究側の数字を再現（差<0.05pt）: {c['reproduced']}",
            f"近い作り方（保有期間）: {nbt}",
            f"分位の単調性: {monot}",
            f"保有の前半 2007-2015 {_st(c.get('sub_2007_2015'))}／後半 2016-2024 {_st(c.get('sub_2016_2024'))}／最良の2年 {dr.get('dropped')} を抜くと {_st(dr.get('stats'))}",
            f"CAPM（保有）: β {c['capm_hold']['beta']}・α {c['capm_hold']['alpha']:+.2f}%/年 t≈{c['capm_hold']['t_approx']}",
            f"独立の作り方: {indt or 'なし'}",
            c5t,
            f"回転率: 研究側の仮定 {c['turnover_assumed']}/年 → 定義（窓・組み直しの間隔・分位）どおりの合成データ {c['turnover_sim']}（入れ替えは窓の移動だけ＝下限）。損益分岐 {c.get('breakeven_turnover_at_0.30pct')}/年（0.30%）・0.50% なら {_st(c.get('net_sim_0.50'))}",
            f"日本の課税口座（20.315%・戦略は毎年実現・指数は最後に一度）の保有期間: 税引後の年率差 {c['after_tax_jp_hold']['diff']:+.2f}pt",
            mtxt,
        ]
        g_own = c['grade_own']
        iss.insert(1, f"自前の格付け: 登録どおり {g_own['as_registered_lag12_assumed_turnover'][0]}／定義どおりの回転率 {g_own['lag12_simulated_turnover'][0]}／NW ラグ 6・12・24 の最悪＋定義どおりの回転率 {g_own['worst_of_lag6_12_24_simulated_turnover'][0]}")
        iss += SPECIFIC.get(cid, [])
        V.append({'name': cid, 'claimed_grade': c['claimed_grade'], 'reproduced': c['reproduced'], 'verified_grade': g, 'verdict': v,
                  'key_numbers': keynum(c), 'issues': iss})
    return V


SPECIFIC = {
    'SQ:MomOffSeason06YrPlus': [
        '判断: S の条件 C3（保有 t≥1.65）は NW ラグ12 で 1.651＝線を 0.001 だけ越える。ラグ6 で 1.640・ラグ24 で 1.628 と落ちる＝S は刃の上。',
        '米国の分位は保有期間でも単調（十分位の順位相関 0.98）で信号そのものは生きているが、市場に対する上乗せは 2022・2007 の2年に集中（抜くと +0.34 t0.22）。大型株（NYSE 20%点超・原論文の等加重）の端は保有期間で負け（幾何差 −1.78）。JKP の同じ主題の米国の三分位は保有 +0.6 t0.4。',
        '一方、米国外は保有期間でも先進国・新興国とも正（t≈2.4・2.2）＝C5 は全期間でも保有でも成り立つ。全期間 t 4.07 は Holm/HLZ の 3.0 は越えるがプログラム全体の線 4.35 に届かない → A に下げる（勝ちは米国外の再現に支えられる形）'],
    'S:ShareIss1Y': [
        '判断: 登録どおりの規則（十分位の最上位）は C3 を NW ラグ 6・12・24 のどれでも越え（1.89・2.00・2.06）、定義どおりの回転率でも費用後に正（C6）。機械的には S のまま。',
        'だが頑丈さが無い: 同じ事前登録の双子（五分位の最上位 SQ:ShareIss1Y）は保有 −0.01（格付け C）、隣の十分位9は −1.38 t−1.78、分位は単調でない（順位相関 0.35）。保有期間の効きは発行した側（第1十分位 −8.1%/年）に集中し、買う側は端の1本だけ。',
        '独立の作り方（French の株数を減らした会社全体 NI<0 の時価加重・JKP chcsho_12m の良い側の三分位）は保有期間 +0.16〜+0.38%/年 t<0.6。前半 t0.78・最良の2年を抜くと t1.31。',
        '米国外の同じ主題（三分位）は保有期間でも先進国 +1.48 t2.55・新興国 +1.69 t1.93＝C5 は強い。→ S ではなく A（C3 の合格は一つの切り方に依存・勝ちの主題は米国外と C3 の二つで支えられる）'],
    'S:ShareIss5Y': [
        '判断: C3 は NW ラグ12 で 1.653＝線を 0.003 だけ越える。ラグ6 では 1.533 で落ちる。C5 は研究側の規則で相手なし（N/A）なので、C3 が落ちると A の道が無く B。',
        '近い作り方: 十分位9 −0.22・五分位の最上位 +0.62 t0.99・第4五分位 −0.79。独立の作り方: JKP eqnpo_12m（Daniel-Titman の相手）の米国の良い側 −0.48・French NI<0 +0.16。最良の2年（2011・2021）を抜くと +0.50 t0.63。',
        '公平のため: JKP eqnpo_12m の米国外は保有でも正（先進国・新興国）だが、研究側の事前登録の規則（訓練の相関≥0.5）で相手にならない（相関 0.12）うえ、その米国版は保有 −0.48＝同じ物ではない。',
        'ShareIss1Y と同じ主題（株数の減少）で独立の証拠ではない。全期間 t 4.59 はプログラムの線 4.35 を越えるが、ほとんどが原論文の標本（1968-2003）の中 → B に下げる'],
    'S:Mom6m': [
        '判断: C3 不合格（保有 t 1.25〜1.39）で A は C5 に頼る。保有期間の上乗せは 2020・2007 の2年だけ（抜くと +0.05・幾何差 −1.18）・前半 2007-2015 は幾何差 −1.71。2020 年の端の超過は +77.5%。',
        '同じ事前登録の双子（五分位の最上位）は −0.21（C）・隣の十分位9は −2.60 t−1.64・大型株の端は −1.35（幾何差 −3.29）。JKP の米国の三分位 ret_6_1 は保有 +0.6 t0.4。',
        'C5 の米国外は全期間では正だが、保有期間では先進国 +0.81 t0.96・新興国 +1.14 t1.06・日本 −1.15。CAPM α +3.05 t0.87（β1.16）。→ 上乗せは頑丈でない（B の定義どおり）'],
    'S:Mom12mOffSeason': [
        '判断: C3 は NW ラグ12 で 1.605（不合格・ラグ24 なら 1.856）。前半・後半とも正で、2020 を抜いても +3.99 t1.35 と勢いの族では最も頑丈。',
        'だが上乗せは十分位の最上位だけ: 第1〜9十分位は保有期間すべて負け、双子の五分位は −0.32（C）・隣の十分位9は −2.61・大型株の端は −0.11（幾何差 −2.14）。JKP の米国の三分位 seas_1_1na は保有 +0.25 t0.17。最良の2年（2007・2024）を抜くと幾何差 +0.38。',
        'C5 の米国外は保有でも正（先進国 +2.25 t1.87）だが、それは三分位の主題で、同じ三分位は米国の保有期間で 0。回転率は定義どおり 4.2/年（研究側の仮定 2.0）で費用後 +3.29 → C6 は残る。→ B（米国の規則の勝ちは一つの切り方に依存）'],
    'S:Mom12m': [
        '判断: C3 は大きく不合格（t 0.71〜0.87）。保有の上乗せは 2020・2007 の2年（抜くと 幾何差 −2.30）・2020 を抜くだけで 幾何差 −0.50。CAPM α +0.92 t0.31（β1.13）＝上げ相場の β。',
        '定義どおりの回転率 2.2/年（研究側 1.0）で費用後の幾何差 +0.44・0.50% なら −0.03・日本の課税口座では −0.46pt＝C6 は刃の上。',
        '隣の十分位9は −3.75 t−2.60・双子の五分位 −1.60・大型株の端 −1.69・JKP の米国の三分位 ret_12_1 は保有 −0.17。French の Hi PRIOR（NYSE の区切り）は保有 +2.62 t0.98 と同じ向きで、2026-08 まで延ばすと +3.29 t1.19。→ B'],
    'SQ:IntMom': [
        '判断: 研究側は回転率を 2.0/年と仮定したが、6か月の窓を毎月組み直す五分位は定義どおりの合成データで 4.3〜4.7/年（下限）。費用後の保有は −0.26%/年・幾何差 −0.77 → C6 不合格＝C。損益分岐は 2.4/年。',
        '研究側の仮定のままでも費用後の幾何差は +0.05（刃の上）。後半 2016-2024 は −0.47・最良の2年を抜くと 幾何差 −0.57・JKP の ret_12_7 と全期間の相関 0.84（研究側も重複の印）。'],
    'S:Mom6mJunk': [
        '判断: C1（訓練 t≥2.0）は NW ラグ12 で 2.007＝線を 0.007 だけ越え、ラグ6 で 1.964・ラグ24 で 1.843 と落ちる。全期間 t 2.93（C7 不合格）。',
        '保有期間の上乗せは一社に寄る: 2020 年の端の超過 +101%、Tesla への当てはめの重み 0.27（相関 0.81）。2023 年も重み 0.26（相関 0.64）だが、Tesla は S&P で 2022-10 に投資適格（BBB）へ上がっており、実時間の『投機的格付けだけ』の規則なら入らない。S&P の格付けは Compustat の格付けファイルが 2017 で終わり、端の銘柄数は 2016 の約75から約50へ減った＝古い格付けのまま使われている疑い（確定はできない）。',
        '前半 2007-2015 は幾何差 −0.64（後半 +19.4）・隣の十分位9 −3.10・双子の五分位の費用後 幾何差 −0.64。→ C（B の条件 C1 が刃の上で、上乗せはデータの時代が怪しい区間と一社に集中）'],
    'SQ:ProbInformedTrading': [
        '判断: 反証。保有期間（2007-2013）は5つの五分位すべてが市場に +8〜+19%/年で勝ち、悪い側（第1五分位 +19.3）ほど大きい（順位相関 −0.9）＝良い側の上乗せは信号ではなく、この予言因子が値を持つ銘柄の集合（小型・低流動性）のもの。信号の向き（第5−第1）は保有期間で −11%/年と原論文と逆。',
        'PIN のデータ（Duarte et al.）は 2012 年で終わる（OAP の Release Notes）＝2014 年以降この規則は実行できない。保有期間は登録の18年のうち7年だけ・後半 2016-2024 は存在しない・20年窓は無い（C4 は欠測＝不合格）。',
        '端の銘柄数は中央値 24 で下限20の近く: 下限を 15 にすると訓練 t 2.28・保有 +6.83 t1.49、25 にすると保有は26か月だけ。最良の2年（2013・2008）を抜くと +2.0 t0.50。0.30% の費用は最小・最も流動性の低い株には甘い。'],
    'P:REV6': [
        '判断: B を確認（主の族で唯一の B・候補の外から追加で検証）。訓練 t は NW ラグ 6・12・24 で 2.02・2.09・2.29 と C1 を保ち、損益分岐の回転率 6.2/年は月次の改訂の和としてありうる範囲。',
        'ただし保有の上乗せは β: β 1.38・CAPM α +0.23 t0.07。最良の2年（2021・2009）を抜くと 幾何差 −1.40。大型株の端 −0.43・隣の十分位9 −0.05・双子の五分位の費用後 幾何差 −0.51。勝ちではない（B のまま・S/A の余地なし）'],
}

CONCLUSION = ('研究側の S 3本・A 4本と B の上位2本（＋主の族の B の REV6）を独立に作り直し、全部の数字を再現した（差<0.05pt）。'
              '反証の後: S は0本。A は2本（SQ:MomOffSeason06YrPlus〔S→A〕・S:ShareIss1Y〔S→A〕）、B は4本（ShareIss5Y〔S→B〕・Mom6m・Mom12mOffSeason・Mom12m〔A→B〕）、C は IntMom（A→C・定義どおりの回転率で費用後に負け）・Mom6mJunk（B→C）・ProbInformedTrading（反証）。主の族の REV6 は B を確認（上乗せは β1.38 で α≈0）。'
              'S の3本はどれも C3 が刃の上（1.651・1.653）か、登録の一つの切り方にだけ依存（双子の五分位・隣の十分位・大型株の端・French/JKP の独立の作り方は 2007 年以降ほぼ0）。'
              '残った A の2本は米国外（JKP の三分位）で保有期間にも正という C5 に支えられるが、米国の上乗せは 2022・2007 の2年、または端の十分位だけに集中し、全期間 t もプログラム全体の線 4.35 に届かない（ShareIss1Y の 4.45 を除く）。'
              '主の族（JKP に無い情報源）の勝ちは無いという研究側の結論は変わらない。')


def M_shift(ym, lag):
    y, m = divmod(ym, 100)
    m += lag
    while m < 1:
        y -= 1; m += 12
    while m > 12:
        y += 1; m -= 12
    return y * 100 + m


def inv_norm(p):
    lo, hi = 0.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if 0.5 * math.erfc(-mid / math.sqrt(2)) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


if __name__ == '__main__':
    main()
