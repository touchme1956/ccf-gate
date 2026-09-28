#!/usr/bin/env python3
"""night/mw_etf_tactical.py — 『市場に勝てる歴史検証』の角度 etf_tactical（読むだけ・門の判定には不使用）

公表済みの戦術的資産配分・ローテーション規則（GEM・GTAA-5・VAA-G4・DAA-G12・セクターの勢い）を、
実在の ETF・投信（生き残りの偏りあり）と、それより前へ延ばす長い代理（French・FRED・AQR・LBMA）で動かし、
French Mkt（上限なしの時価加重・総リターン）に勝つかを out/mw_prereg.json の線（C1〜C8）で裁く。

事前登録: out/mw_etf_tactical_prereg.json（測る前にコミット）。線は結果を見て動かさない。
版: E=ETF だけ／F=実在のファンドだけ（ETF ← 投信）／L=長い代理（ETF ← 投信 ← 指数の代理）。

使い方:
  python3 night/mw_etf_tactical.py --dry     # データの有無・つなぎ目・外れ値・代理と実物の相関だけ（戦略と市場の比較はしない）
  python3 night/mw_etf_tactical.py           # 全部測って out/mw_etf_tactical.json へ
"""
import sys, os, io, json, math, zipfile, subprocess, datetime, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402

END = 202608                      # French の終わり（Yahoo の 2026-09 は途中の月なので使わない）
PREREG = 'mw_etf_tactical_prereg.json'
OUT = 'mw_etf_tactical.json'
C_SIDE = 0.0005                    # 売り・買いそれぞれ 0.05%（= 片道100%あたり 0.10%）
C_SIDE_STRESS = 0.0015             # 片道 0.30%
TAX = 0.20315
FR_FTP = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/'
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


def madd(m, k):
    y, mo = divmod(m // 100 * 12 + m % 100 - 1 + k, 12)
    return y * 100 + mo + 1


# ───────────────────────── データ ─────────────────────────
def cut(d, z=END):
    return {k: v for k, v in d.items() if k <= z}


def yh(t):
    return cut(M.yahoo(t))


def fr_intl(zipname, member):
    """French の国際ファイル（.Dat）の最初の節（Value-Weight Dollar Returns・Not Reqd）の Mkt 列 → {yyyymm: 小数}"""
    b = M.get(FR_FTP + zipname, name='fr_' + zipname)
    z = zipfile.ZipFile(io.BytesIO(b))
    lines = z.read(member).decode('latin-1').splitlines()
    out, started, header = {}, False, ''
    for ln in lines:
        s = ln.split()
        if not s:
            if started:
                break
            continue
        if s[0].isdigit() and len(s[0]) == 6:
            if not started:
                assert 'Dollar' in header and 'Not Reqd' in header, (zipname, member, header)
            started = True
            v = float(s[1])
            if v > -99.9:
                out[int(s[0])] = v / 100
        elif started:
            break
        elif 'Value-Weight' in ln:
            header = ln
    return out


def fred_monthend(sid):
    b = M.get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}', name=f'fred_{sid}.csv')
    me = {}
    for ln in b.decode().splitlines()[1:]:
        d, v = ln.split(',')[:2]
        if v in ('.', ''):
            continue
        me[int(d[:4]) * 100 + int(d[5:7])] = float(v) / 100   # 昇順なので最後の観測日が残る
    return me


def bond_series(sid, N):
    """満期 N 年の額面債を毎月買い替える構成（利率 y_{t-1}・半年払い）。前月と当月の月末利回りがそろう月だけ"""
    y = fred_monthend(sid)
    out = {}
    for m in sorted(y):
        p = madd(m, -1)
        if p not in y:
            continue
        y0, y1 = y[p], max(y[m], 1e-6)
        n = N - 1 / 12
        dsc = (1 + y1 / 2) ** (-2 * n)
        P = y0 / y1 * (1 - dsc) + dsc
        out[m] = P - 1 + y0 / 12
    return cut(out)


def aqr_commodity(rf):
    import openpyxl
    b = M.get('https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Commodities-for-the-Long-Run-Index-Level-Data-Monthly.xlsx',
              name='aqr_commodities_long_run_monthly.xlsx')
    wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
    ws = wb['Commodities for the Long Run']
    out = {}
    for r in ws.iter_rows(values_only=True):
        d, x = r[0], r[1] if len(r) > 1 else None
        if d is None or x is None or isinstance(x, str):
            continue
        if isinstance(d, str):
            try:
                d = datetime.datetime.strptime(d[:10], '%Y-%m-%d')
            except ValueError:
                continue
        m = d.year * 100 + d.month
        if m in rf:
            out[m] = float(x) + rf[m]           # 超過 + T-bill = 担保つき先物の総リターン
    return cut(out)


def lbma_gold():
    j = json.loads(M.get('https://prices.lbma.org.uk/json/gold_pm.json', name='lbma_gold_pm.json'))
    me = {}
    for x in j:
        v = (x.get('v') or [None])[0]
        if v is None or v <= 0:
            continue
        me[int(x['d'][:4]) * 100 + int(x['d'][5:7])] = v
    ks = sorted(me)
    return cut({k: me[k] / me[p] - 1 for p, k in zip(ks, ks[1:]) if madd(p, 1) == k})


def contiguous_tail(d, name):
    """END で終わる連続した月の塊だけ残す（途中に欠けがあればそれより前は捨てて記録する）"""
    ks = sorted(d)
    if not ks:
        return {}, None
    start = ks[0]
    dropped = None
    for a, b in zip(ks, ks[1:]):
        if madd(a, 1) != b:
            start = b
            dropped = (ks[0], a)
    if dropped:
        log(f'  ⚠ {name}: 欠けあり → {dropped[0]}〜{dropped[1]} を捨てて {start} から使う')
    return {k: v for k, v in d.items() if k >= start}, dropped


def load_all():
    ff = M.ff_factors()
    rf = cut(ff['rf'])
    mkt = cut(ff['mkt'])
    src, meta = {}, {}
    tick = ['SPY', 'VFINX', 'QQQ', 'RYOCX', '^NDX', 'IWM', 'NAESX', 'EFA', 'VTMGX', 'VEU', 'VGTSX', 'VGK', 'VEURX', 'EWJ',
            'EEM', 'VWO', 'VEIEX', 'AGG', 'BND', 'VBMFX', 'LQD', 'VWESX', 'IEF', 'VFITX', 'SHY', 'VFISX', 'TLT', 'VUSTX',
            'HYG', 'VWEHX', 'VNQ', 'VGSIX', 'FRESX', 'GSG', 'PCRIX', 'GLD', 'DBC',
            'XLB', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLU', 'XLV', 'XLY',
            'FSDPX', 'FSENX', 'FIDSX', 'FSDAX', 'FSRFX', 'FSPTX', 'FDFAX', 'FSUTX', 'FSPHX', 'FSCPX', '^SP500TR']
    for t in tick:
        src[t] = yh(t)
    # 代理
    src['FF_MKT'] = mkt
    src['NDX_PX_DIV'] = {k: v + 0.005 / 12 for k, v in src['^NDX'].items()}
    src['FR_EAFE'] = cut(fr_intl('F-F_International_Indices.zip', 'Ind_all.Dat'))
    src['FR_EUROPE'] = cut(fr_intl('F-F_International_Indices.zip', 'Ind_Eur_With_UK.Dat'))
    src['FR_JAPAN'] = cut(fr_intl('F-F_International_Countries.zip', 'Japan.Dat'))
    em = M.french_tables('Emerging_5_Factors')
    emt = [v for v in em.values() if v['freq'] == 'monthly'][0]
    ci = {c: i for i, c in enumerate(emt['cols'])}
    src['FR_EM'] = cut({d: (row[ci['Mkt-RF']] + row[ci['RF']]) / 100 for d, row in emt['data'].items()
                        if row[ci['Mkt-RF']] is not None and row[ci['RF']] is not None})
    src['UST2'] = bond_series('DGS2', 2)
    src['UST5'] = bond_series('DGS5', 5)
    src['UST10'] = bond_series('DGS10', 10)
    src['UST20'] = bond_series('DGS20', 20)
    src['AQR_COM'] = aqr_commodity(rf)
    src['LBMA_GOLD'] = lbma_gold()
    # XLI の投信代理: FSDAX と FSRFX の 50/50（毎月リバランス）
    src['FSDAX_FSRFX'] = {k: 0.5 * src['FSDAX'][k] + 0.5 * src['FSRFX'][k] for k in src['FSDAX'] if k in src['FSRFX']}
    # 第2族: Fidelity Select 業種ファンド（事前登録2）と French 30業種（Other を除く29）
    for t in FSEL:
        if t not in src:
            src[t] = yh(t)
    ind30 = M.french_series('30_Industry_Portfolios', 'Value Weight')
    for c in ind30:
        if c.strip().lower() != 'other':
            src['FR30_' + c.strip()] = cut(ind30[c])
    # 事前登録3: 死んだ Select（AV・手で写した値。out/_mw_cache/av_dead_select_{T}.csv）
    import csv as _csv
    for t in DEAD:
        rows = sorted(_csv.DictReader(open(os.path.join(M.CACHE, f'av_dead_select_{t}.csv'))), key=lambda r: r['date'])
        px = {int(r['date'][:4]) * 100 + int(r['date'][5:7]): float(r['adj']) for r in rows}
        ks = sorted(px)
        src['AV_' + t] = cut({k: px[k] / px[p] - 1 for p, k in zip(ks, ks[1:]) if madd(p, 1) == k})
    for t in ETFIND:
        if t not in src:
            src[t] = yh(t)
    # French 10業種（Other を除く9）
    ind = M.french_series('10_Industry_Portfolios', 'Value Weight')
    for c in ['NoDur', 'Durbl', 'Manuf', 'Enrgy', 'HiTec', 'Telcm', 'Shops', 'Hlth', 'Utils']:
        src['FR10_' + c] = cut(ind[c])
    for k in list(src):
        src[k], dr = contiguous_tail(src[k], k)
        ks = sorted(src[k])
        meta[k] = {'from': ks[0] if ks else None, 'to': ks[-1] if ks else None, 'n': len(ks), 'dropped_before_gap': dr}
    return src, rf, mkt, meta


# ───────────────────────── 枠と版 ─────────────────────────
SLOTS = {
    'US': (['SPY'], ['VFINX'], 'FF_MKT'),
    'NDX': (['QQQ'], ['RYOCX'], 'NDX_PX_DIV'),
    'SMALL': (['IWM'], ['NAESX'], None),
    'EAFE': (['EFA'], ['VTMGX'], 'FR_EAFE'),
    'ACWXUS': (['VEU'], ['VGTSX'], 'FR_EAFE'),
    'EUROPE': (['VGK'], ['VEURX'], 'FR_EUROPE'),
    'JAPAN': (['EWJ'], [], 'FR_JAPAN'),
    'EM_EEM': (['EEM'], ['VEIEX'], 'FR_EM'),
    'EM_VWO': (['VWO'], ['VEIEX'], 'FR_EM'),
    'AGG': (['AGG'], ['VBMFX'], 'UST5'),
    'BND': (['BND', 'AGG'], ['VBMFX'], 'UST5'),
    'LQD': (['LQD'], ['VWESX'], None),
    'IEF': (['IEF'], ['VFITX'], 'UST10'),
    'SHY': (['SHY'], ['VFISX'], 'UST2'),
    'TLT': (['TLT'], ['VUSTX'], 'UST20'),
    'HYG': (['HYG'], ['VWEHX'], None),
    'VNQ': (['VNQ'], ['VGSIX', 'FRESX'], None),
    'GSG': (['GSG'], ['PCRIX'], 'AQR_COM'),
    'GLD': (['GLD'], [], 'LBMA_GOLD'),
    'TECH': (['XLK'], ['FSPTX'], None),
    'XLB': (['XLB'], ['FSDPX'], None), 'XLE': (['XLE'], ['FSENX'], None), 'XLF': (['XLF'], ['FIDSX'], None),
    'XLI': (['XLI'], ['FSDAX_FSRFX'], None), 'XLK': (['XLK'], ['FSPTX'], None), 'XLP': (['XLP'], ['FDFAX'], None),
    'XLU': (['XLU'], ['FSUTX'], None), 'XLV': (['XLV'], ['FSPHX'], None), 'XLY': (['XLY'], ['FSCPX'], None),
}
FSEL = ['FSPTX', 'FSENX', 'FIDSX', 'FSUTX', 'FSPHX', 'FSDAX', 'FDLSX', 'FSLBX', 'FSCHX', 'FDFAX', 'FSELX', 'FSTCX', 'FSCSX', 'FDCPX',
        'FSAGX', 'FBIOX', 'FSVLX', 'FSPCX', 'FSRPX', 'FSAVX', 'FSHCX', 'FBMPX', 'FSRBX', 'FSHOX', 'FSDPX', 'FSRFX', 'FSLEX', 'FSCPX',
        'FNARX', 'FBSOX', 'FSMEX', 'FWRLX', 'FPHAX']
DEAD = ['FSESX', 'FSNGX', 'FSAIX', 'FSDCX', 'FCYIX', 'FSCGX']   # 事前登録3: 合併・廃止された Select（Alpha Vantage・1999-12〜）
ETFIND = ['IYW', 'IYF', 'IYH', 'IYE', 'IYM', 'IYJ', 'IYC', 'IYK', 'IDU', 'IYZ', 'IYR', 'IYT', 'IAT', 'IAI', 'IAK', 'IHF', 'IHI', 'IHE',
          'ITA', 'ITB', 'IEZ', 'IEO', 'SOXX', 'IGV', 'IGE', 'IBB', 'XBI', 'XHB', 'XRT', 'KBE', 'KRE', 'KIE', 'KCE', 'XSD', 'XPH', 'XME',
          'XOP', 'XES', 'XAR', 'XHE', 'XHS', 'XTL', 'XTN', 'XSW']
SECT_EF = ['XLB', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLU', 'XLV', 'XLY']
SECT_L = ['FR10_' + c for c in ['NoDur', 'Durbl', 'Manuf', 'Enrgy', 'HiTec', 'Telcm', 'Shops', 'Hlth', 'Utils']]


def splice(src, slot, ver):
    etf, fund, proxy = SLOTS[slot]
    order = list(etf)
    if ver in ('F', 'L'):
        order += list(fund)
    if ver == 'L' and proxy:
        order.append(proxy)
    months = sorted(set().union(*[set(src[n]) for n in order])) if order else []
    out, used = {}, {}
    for m in months:
        for n in order:
            if m in src[n]:
                out[m] = src[n][m]
                used.setdefault(n, [m, m])[1] = m
                break
    out, _ = contiguous_tail(out, f'{slot}[{ver}]')
    return out, {n: v for n, v in used.items()}


def build_version(src, rf, ver, slots):
    R = {'TBILL': rf}
    seg = {}
    for s in slots:
        if s == 'TBILL':
            continue
        if s.startswith('FR10_') or s.startswith('FR30_') or s.startswith('AV_') or s == 'FF_MKT' or s in FSEL or s in ETFIND:
            R[s] = src[s]
            seg[s] = {s: [min(src[s]), max(src[s])]}
            continue
        R[s], seg[s] = splice(src, s, ver)
    return R, seg


# ───────────────────────── 信号（t までしか見ない） ─────────────────────────
class Hist:
    """t 月末までのリターンしか返さない窓（後知恵を構造で防ぐ）"""
    def __init__(self, R, t):
        self.R, self.t = R, t

    def get(self, s, m):
        if m > self.t:
            raise RuntimeError(f'後知恵: {s} {m} > {self.t}')
        return self.R[s].get(m)

    def cum(self, s, k):
        v = 1.0
        for j in range(k):
            x = self.get(s, madd(self.t, -j))
            if x is None:
                return None
            v *= 1 + x
        return v - 1

    def w13612(self, s):
        p = [self.cum(s, k) for k in (1, 3, 6, 12)]
        if None in p:
            return None
        return 12 * p[0] + 4 * p[1] + 2 * p[2] + p[3]

    def blend(self, s):
        p = [self.cum(s, k) for k in (1, 3, 6, 12)]
        return None if None in p else sum(p) / 4

    def above_sma(self, s, n=10):
        lv, L = [1.0], 1.0
        for j in range(n - 2, -1, -1):          # t−(n−2) … t の n−1 個のリターン → n 個の水準
            x = self.get(s, madd(self.t, -j))
            if x is None:
                return None
            L *= 1 + x
            lv.append(L)
        return lv[-1] > sum(lv) / n

    def vol(self, s, k=12):
        xs = [self.get(s, madd(self.t, -j)) for j in range(k)]
        return None if None in xs else S.stdev(xs)

    def have(self, s):
        return self.get(s, self.t) is not None


def argmax(H, names, score):
    sc = []
    for i, n in enumerate(names):
        v = score(n)
        if v is None:
            return None
        sc.append((-v, i, n))
    return sorted(sc)[0][2]


def topk(H, names, score, k):
    sc = []
    for i, n in enumerate(names):
        v = score(n)
        if v is None:
            return None
        sc.append((-v, i, n))
    return [n for _, _, n in sorted(sc)[:k]]


def r_gem(H):
    u, x, b = H.cum('US', 12), H.cum('ACWXUS', 12), H.cum('TBILL', 12)
    if None in (u, x, b):
        return None
    if u > b:
        return {'US': 1.0} if u >= x else {'ACWXUS': 1.0}
    return {'AGG': 1.0}


def r_gem_rel(H):
    u, x = H.cum('US', 12), H.cum('ACWXUS', 12)
    if None in (u, x):
        return None
    return {'US': 1.0} if u >= x else {'ACWXUS': 1.0}


def r_gtaa(H):
    w = {}
    for s in ['US', 'EAFE', 'IEF', 'GSG', 'VNQ']:
        a = H.above_sma(s)
        if a is None or not H.have('TBILL'):
            return None
        k = s if a else 'TBILL'
        w[k] = w.get(k, 0) + 0.2
    return w


def r_vaa(H):
    risky, cash = ['US', 'EAFE', 'EM_EEM', 'AGG'], ['LQD', 'IEF', 'SHY']
    m = {s: H.w13612(s) for s in risky + cash}
    if None in m.values():
        return None
    if all(m[s] > 0 for s in risky):
        return {argmax(H, risky, lambda s: m[s]): 1.0}
    return {argmax(H, cash, lambda s: m[s]): 1.0}


def r_daa(H):
    risky = ['US', 'SMALL', 'NDX', 'EUROPE', 'JAPAN', 'EM_VWO', 'VNQ', 'GSG', 'GLD', 'TLT', 'HYG', 'LQD']
    canary, cash = ['EM_VWO', 'BND'], ['SHY', 'IEF', 'LQD']
    m = {s: H.w13612(s) for s in set(risky + canary + cash)}
    if None in m.values():
        return None
    b = sum(1 for c in canary if m[c] <= 0)
    cf = b / 2
    w = {}
    if cf < 1:
        for s in topk(H, risky, lambda s: m[s], 6):
            w[s] = w.get(s, 0) + (1 - cf) / 6
    if cf > 0:
        c = argmax(H, cash, lambda s: m[s])
        w[c] = w.get(c, 0) + cf
    return w


def mk_sector(names, k=3, score='r12', absf=False):
    def f(H):
        if score == 'r12':
            sc = lambda s: H.cum(s, 12)
        else:
            sc = H.blend
        top = topk(H, names, sc, k)
        if top is None:
            return None
        w = {}
        if absf:
            b = H.cum('TBILL', 12)
            if b is None:
                return None
        for s in top:
            key = s
            if absf and not (H.cum(s, 12) > b):
                key = 'TBILL'
            w[key] = w.get(key, 0) + 1 / k
        return w
    return f


def alive_next(H, s):
    """事前登録3: t+1 月にもファンドが存在するか（合併・廃止の日付だけを見る。リターンは見ない）"""
    return bool(H.R.get(s)) and max(H.R[s]) > H.t


def mk_sector_dyn(names, k, score='r12', min_n=20, alive=False):
    """その月に12か月の窓がそろったものだけから上位 k（対象が min_n 未満の月は作らない＝始まらない）"""
    def f(H):
        sc = (lambda s: H.cum(s, 12)) if score == 'r12' else H.blend
        avail = [s for s in names if H.R.get(s) and (not alive or alive_next(H, s)) and sc(s) is not None]
        if len(avail) < min_n:
            return None
        top = topk(H, avail, sc, k)
        return None if top is None else {s: 1 / k for s in top}
    return f


def mk_ew_dyn(names, min_n=20, alive=False):
    def f(H):
        avail = [s for s in names if H.R.get(s) and (not alive or alive_next(H, s)) and H.cum(s, 12) is not None]
        if len(avail) < min_n:
            return None
        return {s: 1 / len(avail) for s in avail}
    return f


def mk_switch(a, b):
    def f(H):
        x, y = H.cum(a, 12), H.cum(b, 12)
        if None in (x, y):
            return None
        return {a: 1.0} if x > y else {b: 1.0}
    return f


def r_eq5(H):
    names = ['US', 'NDX', 'SMALL', 'EAFE', 'EM_EEM']
    top = topk(H, names, lambda s: H.cum(s, 12), 1)
    return None if top is None else {top[0]: 1.0}


def mk_static(w):
    def f(H):
        return None if not all(H.have(s) for s in w) else dict(w)
    return f


def r_rp(H):
    a, b = H.vol('US'), H.vol('IEF')
    if None in (a, b) or a <= 0 or b <= 0:
        return None
    ia, ib = 1 / a, 1 / b
    return {'US': ia / (ia + ib), 'IEF': ib / (ia + ib)}


def mk_ew(names):
    def f(H):
        return None if not all(H.have(s) for s in names) else {s: 1 / len(names) for s in names}
    return f


# ───────────────────────── 走らせる ─────────────────────────
def run(R, rule, z=END, dynamic=False):
    """月末 t の信号で t+1 を持つ。戻り値: gross, net, net_stress, 重みの記録, 売買量（Σ|Δw|）
    dynamic=True（途中で消えるファンドを含む族）: 終わりは END。持つファンドは必ず翌月の値がある（規則が存在を確かめる）"""
    if not dynamic:
        z = min([z] + [max(v) for v in R.values() if v])      # 必要な系列のうち最も早く終わる月まで（0で埋めない）
    months = sorted(set().union(*[set(v) for v in R.values()]))
    months = [m for m in months if m <= z]
    gross, trades, wpath = {}, {}, {}
    w_prev_drift = None
    started = False
    for t in months:
        nxt = madd(t, 1)
        if nxt > z:
            break
        try:
            w = rule(Hist(R, t))
        except KeyError:
            w = None
        if w is None:
            if started:
                raise RuntimeError(f'開始後に信号が作れない: {t}')
            continue
        if not all(nxt in R[s] for s in w):
            if started:
                raise RuntimeError(f'開始後に保有の翌月リターンが無い: {t}→{nxt} {[s for s in w if nxt not in R[s]]}')
            continue
        tot = sum(w.values())
        assert abs(tot - 1) < 1e-9, (t, w)
        tr = 0.0
        if started and w_prev_drift is not None:
            keys = set(w) | set(w_prev_drift)
            tr = sum(abs(w.get(s, 0) - w_prev_drift.get(s, 0)) for s in keys)
        started = True
        rp = sum(w[s] * R[s][nxt] for s in w)
        gross[nxt] = rp
        trades[nxt] = tr
        wpath[t] = w
        w_prev_drift = {s: w[s] * (1 + R[s][nxt]) / (1 + rp) for s in w}
    net = {m: gross[m] - C_SIDE * trades[m] for m in gross}
    net_s = {m: gross[m] - C_SIDE_STRESS * trades[m] for m in gross}
    return gross, net, net_s, wpath, trades


def tax_sim(R, wpath, a, z=END):
    """日本の課税口座: 売却益 20.315%・年内通算・損失3年繰越・平均取得単価。a 月から始めて z で全部売った税引後の年率"""
    ms = sorted(m for m in wpath if a <= madd(m, 1) <= z)
    if len(ms) < 24:
        return None
    t0 = madd(ms[0], 0)
    w0 = wpath[t0]
    val = {s: w0[s] for s in w0}
    basis = dict(val)
    carry = []                                  # (年, 損失)
    yr_gain, cur_year = 0.0, None

    def settle(year, gain):
        nonlocal carry
        carry = [(y, l) for y, l in carry if year - y <= 3]
        if gain < 0:
            carry.append((year, -gain))
            return 0.0
        rem = gain
        newc = []
        for y, l in carry:
            use = min(l, rem)
            rem -= use
            if l - use > 1e-15:
                newc.append((y, l - use))
        carry = newc
        return rem * TAX

    n = 0
    for t in ms:
        m = madd(t, 1)
        y = t // 100                            # 売買は t 月末＝その年の実現損益
        if cur_year is None:
            cur_year = y
        if y != cur_year:                       # 前の年の売買が全部済んだ＝年の精算
            tax = settle(cur_year, yr_gain)
            tv = sum(val.values())
            if tax > 0 and tv > 0:
                f = 1 - tax / tv
                val = {s: v * f for s, v in val.items()}
                basis = {s: b * f for s, b in basis.items()}
            yr_gain, cur_year = 0.0, y
        # 目標へ（t 月末に決めた重み）
        w = wpath[t]
        tv = sum(val.values())
        tgt = {s: w[s] * tv for s in w}
        for s in set(val) | set(tgt):
            cv, nv = val.get(s, 0.0), tgt.get(s, 0.0)
            if nv < cv - 1e-15:                 # 売り
                sold = cv - nv
                b = basis.get(s, 0.0)
                gain = sold * (1 - b / cv) if cv > 0 else 0.0
                yr_gain += gain
                basis[s] = b * (nv / cv) if cv > 0 else 0.0
            elif nv > cv + 1e-15:               # 買い
                basis[s] = basis.get(s, 0.0) + (nv - cv)
            val[s] = nv
        val = {s: v * (1 + R[s][m]) for s, v in val.items() if v > 0}
        basis = {s: basis.get(s, 0.0) for s in val}
        n += 1
    # 最後に全部売る
    unreal = sum(val[s] - basis[s] for s in val)
    tax = settle(cur_year, yr_gain + unreal)
    final = sum(val.values()) - tax
    return math.exp(math.log(final) * 12 / n) - 1, n


def bh_tax(r, a, z=END):
    ks = sorted(k for k in r if a <= k <= z)
    v = 1.0
    for k in ks:
        v *= 1 + r[k]
    final = v - max(0.0, v - 1) * TAX
    return math.exp(math.log(final) * 12 / len(ks)) - 1


# ───────────────────────── C5: JKP GICS ─────────────────────────
COUNTRIES = ['jpn', 'gbr', 'can', 'fra', 'deu', 'aus', 'che']


def jkp_gics(country, rf):
    url = f'https://jkpfactors-data.s3.amazonaws.com/public/industry/%5B{country}%5D_%5Bgics%5D_%5Bmonthly%5D_%5Bvw%5D.zip'
    b = M.get(url, name=f'jkp_industry_{country}_gics_vw_monthly.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    import csv
    out = {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        m = int(x['date'][:4]) * 100 + int(x['date'][5:7])
        if m in rf:
            out.setdefault('G' + x['gics'], {})[m] = float(x['ret']) + rf[m]
    return out


def gics_rule(k, score, absf):
    """その月に信号の窓がそろったセクターだけから上位 k（k+1 未満しか無い月は作らない）"""
    def f(H):
        names = [s for s in H.R if s.startswith('G')]
        avail = []
        for s in names:
            v = H.cum(s, 12) if score == 'r12' else H.blend(s)
            if v is not None:
                avail.append(s)
        if len(avail) < k + 1:
            return None
        return mk_sector(avail, k, score, absf)(H)
    return f


def repl_sector(rf, k, score, absf, cache):
    res, pos, n = {}, 0, 0
    for c in COUNTRIES:
        if c not in cache:
            cache[c] = (jkp_gics(c, rf), {m: v + rf[m] for m, v in M.jkp_mkt(c, 'vw').items() if m in rf})
        G, mk = cache[c]
        R = dict(G)
        R['TBILL'] = rf
        g, _, _, _, _ = run_loose(R, gics_rule(k, score, absf), z=202512)
        st = M.excess_stats(g, mk)
        if st is None:
            res[c] = None
            continue
        n += 1
        pos += 1 if st['ex_ann'] > 0 else 0
        res[c] = {'ex_ann': st['ex_ann'], 't': st['t'], 'from': st['from'], 'to': st['to'], 'cagr_diff': st['cagr_diff']}
    return {'regions': n, 'positive': pos, 'by_country': res}


def run_loose(R, rule, z):
    """GICS 用: 開始後に一時的に信号が作れない月があっても止めない（その月は持たない＝記録しない・0で埋めない）"""
    months = sorted(set().union(*[set(v) for v in R.values() if v]))
    gross = {}
    for t in months:
        nxt = madd(t, 1)
        if nxt > z:
            break
        w = rule(Hist(R, t))
        if w is None or not all(nxt in R[s] for s in w):
            continue
        gross[nxt] = sum(w[s] * R[s][nxt] for s in w)
    return gross, None, None, None, None


# ───────────────────────── 仕様 ─────────────────────────
SRC_NAMES = []
POSTPUB = {'H1': 201101, 'H2': 201101, 'H3': 201101, 'H4': 201101, 'E1': 201101, 'E2': 201101, 'E3': 201101, 'E4': 201101, 'G1': 201101, 'G2': 201101, 'G3': 201101, 'G4': 201101, 'G6': 201101, 'G7': 201101, 'P1': 201501, 'P2': 200801, 'P3': 201801, 'P4': 201901, 'P5': 201101, 'X3': 201101, 'X4': 201101,
           'X5': 201501, 'X7': 201101}


def specs():
    out = []

    def add(rid, fam, desc, rule_fn, slots, timing, versions=('L', 'F', 'E'), sector=None, repl=None, alloc=False):
        for v in versions:
            out.append(dict(id=f'{rid}_{v}', rule=rid.split('_')[0], family=fam, version=v, description=desc,
                            rule_fn=rule_fn(v), slots=slots(v), timing=timing, repl=repl, alloc=alloc))

    sec = lambda v: SECT_L if v == 'L' else SECT_EF
    add('P1_GEM', 'primary', 'GEM（Antonacci 2014）: 米国株>T-bill なら米国/米国外の強い方、そうでなければ総合債券', lambda v: r_gem,
        lambda v: ['US', 'ACWXUS', 'AGG'], True, alloc=True)
    add('P2_GTAA5', 'primary', 'GTAA-5（Faber 2007）: 5資産×20%、10か月線より上なら保有・下なら T-bill', lambda v: r_gtaa,
        lambda v: ['US', 'EAFE', 'IEF', 'GSG', 'VNQ'], True, alloc=True)
    add('P3_VAA', 'primary', 'VAA-G4（Keller-Keuning 2017）: 攻め4つが全部 13612W>0 なら最強の1つ、そうでなければ守り3つの最強', lambda v: r_vaa,
        lambda v: ['US', 'EAFE', 'EM_EEM', 'AGG', 'LQD', 'IEF', 'SHY'], True, alloc=True)
    add('P4_DAA', 'primary', 'DAA-G12（Keller-Keuning 2018）: カナリア VWO・BND の悪い数で現金比率、攻め12の上位6', lambda v: r_daa,
        lambda v: ['US', 'SMALL', 'NDX', 'EUROPE', 'JAPAN', 'EM_VWO', 'VNQ', 'GSG', 'GLD', 'TLT', 'HYG', 'LQD', 'BND', 'SHY', 'IEF'], True, alloc=True)
    add('P5_SECT3', 'primary', 'セクターの勢い（Faber 2010）: 9セクターの12か月リターン上位3を等分', lambda v: mk_sector(sec(v), 3),
        sec, False, repl=(3, 'r12', False))
    # 参照
    add('R1_6040', 'reference', '参照: 60/40（US 60・AGG 40・毎月）', lambda v: mk_static({'US': 0.6, 'AGG': 0.4}),
        lambda v: ['US', 'AGG'], True, alloc=True)
    add('R2_RP', 'reference', '参照: 逆ボラの株債（US・IEF）', lambda v: r_rp, lambda v: ['US', 'IEF'], True, alloc=True)
    add('R3_EW9', 'reference', '参照: 9セクター等分', lambda v: mk_ew(sec(v)), sec, False)
    add('R4_BH', 'reference', '参照: US 枠を買って持つ', lambda v: mk_static({'US': 1.0}), lambda v: ['US'], False, versions=('F', 'E'))
    # 探索
    add('X1_NDXUS', 'exploratory', '探索: NASDAQ100 と S&P500 の12か月の強い方', lambda v: mk_switch('NDX', 'US'),
        lambda v: ['NDX', 'US'], False)
    add('X2_TECHUS', 'exploratory', '探索: テック（L=French HiTec・F/E=FSPTX→XLK）と市場の12か月の強い方',
        lambda v: mk_switch('FR10_HiTec', 'FF_MKT') if v == 'L' else mk_switch('TECH', 'US'),
        lambda v: ['FR10_HiTec', 'FF_MKT'] if v == 'L' else ['TECH', 'US'], False)
    add('X3_SECT3BL', 'exploratory', '探索: セクター上位3（(r1+r3+r6+r12)/4）', lambda v: mk_sector(sec(v), 3, 'blend'), sec, False,
        repl=(3, 'blend', False))
    add('X4_SECT3ABS', 'exploratory', '探索: セクター上位3（r12）＋ T-bill 以下なら現金', lambda v: mk_sector(sec(v), 3, 'r12', True), sec, True,
        repl=(3, 'r12', True))
    add('X5_GEMREL', 'exploratory', '探索: GEM の相対だけ（米国か米国外の強い方・常に株）', lambda v: r_gem_rel, lambda v: ['US', 'ACWXUS'], False)
    add('X6_EQ5', 'exploratory', '探索: 株5枠（S&P500・NASDAQ100・小型・先進国・新興国）の12か月最強の1つ', lambda v: r_eq5,
        lambda v: ['US', 'NDX', 'SMALL', 'EAFE', 'EM_EEM'], False)
    for k in (1, 2, 4):
        add(f'X7_SECTK{k}', 'exploratory', f'探索（感度）: セクター上位{k}（r12・等分）', lambda v, k=k: mk_sector(sec(v), k), sec, False,
            repl=(k, 'r12', False))
    # 第2族（事前登録2）: Fidelity Select 業種ファンド・French 30 の紙の上の類似
    fr30 = lambda: [n for n in SRC_NAMES if n.startswith('FR30_')]
    one = lambda **kw: out.append(dict(timing=False, alloc=False, **kw))
    for k, kg in ((3, 1), (6, 2)):
        for sc, lab in (('r12', 'R12'), ('blend', 'BL')):
            gid = {('r12', 3): 'G1', ('r12', 6): 'G2', ('blend', 3): 'G3', ('blend', 6): 'G4'}[(sc, k)]
            one(id=f'{gid}_FSEL_K{k}_{lab}', rule=gid, family='exploratory2', version='F',
                description=f'探索2: Fidelity Select 業種ファンド（実在・約32本）の{"12か月" if sc == "r12" else "(r1+r3+r6+r12)/4"}上位{k}本を等分',
                rule_fn=mk_sector_dyn(FSEL, k, sc, 20), slots=list(FSEL), repl=(kg, sc, False))
        gid = {3: 'G6', 6: 'G7'}[k]
        one(id=f'{gid}_FR30_K{k}_R12', rule=gid, family='exploratory2', version='L',
            description=f'探索2（紙の上の類似）: French 30業種（Other 除く29）の12か月上位{k}を、Fidelity と同じ月から',
            rule_fn=mk_sector_dyn(fr30(), k, 'r12', 29), slots=fr30(), repl=(kg, 'r12', False), align_to='G1_FSEL_K3_R12')
    one(id='G5_FSEL_EW', rule='G5', family='reference2', version='F', description='参照2: Fidelity Select を全部等分',
        rule_fn=mk_ew_dyn(FSEL, 20), slots=list(FSEL), repl=None)
    # 第3族（事前登録3）: 死んだ Select 6本を足す／第4族: 業種 ETF
    fseld = list(FSEL) + ['AV_' + t for t in DEAD]
    for (k, kg, sc, lab, hid, eid) in ((3, 1, 'r12', 'R12', 'H1', 'E1'), (6, 2, 'r12', 'R12', 'H2', 'E2'),
                                       (3, 1, 'blend', 'BL', 'H3', 'E3'), (6, 2, 'blend', 'BL', 'H4', 'E4')):
        one(id=f'{hid}_FSELD_K{k}_{lab}', rule=hid, family='exploratory3', version='F', dynamic=True,
            description=f'探索3: Fidelity Select＋合併・廃止6本（生き残りの偏りを直す）の{"12か月" if sc == "r12" else "(r1+r3+r6+r12)/4"}上位{k}本',
            rule_fn=mk_sector_dyn(fseld, k, sc, 20, alive=True), slots=fseld, repl=(kg, sc, False))
        one(id=f'{eid}_ETF_K{k}_{lab}', rule=eid, family='exploratory4', version='E', dynamic=True,
            description=f'探索4: 実在の業種 ETF（iShares・SPDR 44本）の{"12か月" if sc == "r12" else "(r1+r3+r6+r12)/4"}上位{k}本',
            rule_fn=mk_sector_dyn(ETFIND, k, sc, 20, alive=True), slots=list(ETFIND), repl=(kg, sc, False))
    one(id='H5_FSELD_EW', rule='H5', family='reference3', version='F', dynamic=True, description='参照3: Fidelity Select＋死んだ6本を全部等分',
        rule_fn=mk_ew_dyn(fseld, 20, alive=True), slots=fseld, repl=None)
    one(id='E5_ETF_EW', rule='E5', family='reference4', version='E', dynamic=True, description='参照4: 業種 ETF を全部等分',
        rule_fn=mk_ew_dyn(ETFIND, 20, alive=True), slots=list(ETFIND), repl=None)
    return out


# ───────────────────────── 乾いた確認（戦略と市場は比べない） ─────────────────────────
def corr_overlap(a, b):
    ks = sorted(set(a) & set(b))
    if len(ks) < 24:
        return None
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'corr': round(M.corr([a[k] for k in ks], [b[k] for k in ks]), 3),
            'cagr_a': round(M.cagr([a[k] for k in ks]) * 100, 2), 'cagr_b': round(M.cagr([b[k] for k in ks]) * 100, 2)}


PAIRS = [('UST10', 'VFITX'), ('UST10', 'IEF'), ('UST20', 'VUSTX'), ('UST20', 'TLT'), ('UST5', 'VBMFX'), ('UST5', 'AGG'),
         ('UST2', 'VFISX'), ('UST2', 'SHY'), ('FR_EAFE', 'VTMGX'), ('FR_EAFE', 'EFA'), ('FR_EAFE', 'VGTSX'), ('VGTSX', 'VEU'),
         ('FR_EM', 'VEIEX'), ('VEIEX', 'EEM'), ('VEIEX', 'VWO'), ('FR_EUROPE', 'VEURX'), ('VEURX', 'VGK'), ('FR_JAPAN', 'EWJ'),
         ('AQR_COM', 'GSG'), ('AQR_COM', 'DBC'), ('PCRIX', 'GSG'), ('LBMA_GOLD', 'GLD'), ('FRESX', 'VGSIX'), ('VGSIX', 'VNQ'),
         ('NDX_PX_DIV', 'QQQ'), ('RYOCX', 'QQQ'), ('NAESX', 'IWM'), ('VWESX', 'LQD'), ('VWEHX', 'HYG'), ('VBMFX', 'AGG'),
         ('VFINX', 'SPY'), ('VFINX', '^SP500TR'), ('FF_MKT', 'VFINX'),
         ('FSDPX', 'XLB'), ('FSENX', 'XLE'), ('FIDSX', 'XLF'), ('FSDAX_FSRFX', 'XLI'), ('FSPTX', 'XLK'), ('FDFAX', 'XLP'),
         ('FSUTX', 'XLU'), ('FSPHX', 'XLV'), ('FSCPX', 'XLY')]


def dry_checks(src, meta, with_cagr=False):
    out = {'series': meta, 'outliers': {}, 'pairs': {}}
    for k, d in src.items():
        o = [(m, round(v * 100, 1)) for m, v in sorted(d.items()) if abs(v) > 0.40]
        if o:
            out['outliers'][k] = o
    for a, b in PAIRS:
        c = corr_overlap(src[a], src[b])
        if c and not with_cagr:
            c = {x: y for x, y in c.items() if not x.startswith('cagr')}
        out['pairs'][f'{a}~{b}'] = c
    return out


# ───────────────────────── 本体 ─────────────────────────
def git_sha(path):
    try:
        return subprocess.check_output(['git', '-C', M.BASE, 'log', '-n1', '--format=%H', '--', path], text=True).strip() or None
    except Exception:
        return None


def summarize_alloc(wpath, a=None):
    cnt = {}
    n = 0
    for t, w in wpath.items():
        if a and madd(t, 1) < a:
            continue
        n += 1
        for s, x in w.items():
            cnt[s] = cnt.get(s, 0) + x
    return {s: round(v / n, 3) for s, v in sorted(cnt.items(), key=lambda x: -x[1])} if n else {}


def diag_post_hoc(src, rf, mkt, runs):
    """事後（判定に使わない）: 紙の上（French 9業種）と実物（SPDR）のセクターの勢いの差はどこから来たか"""
    out = {'label': '事後の診断（結果を見た後に作った・判定には使わない）'}
    def contrib(rid, a=M.HOLD_START):
        if rid not in runs:
            return None
        R, wpath, g, n = runs[rid]
        c, cnt, nmo = {}, {}, 0
        for t, w in wpath.items():
            m = madd(t, 1)
            if m < a or m not in mkt:
                continue
            nmo += 1
            for s_, x in w.items():
                c[s_] = c.get(s_, 0) + x * (R[s_][m] - mkt[m])
                cnt[s_] = cnt.get(s_, 0) + x
        return {s_: {'avg_weight': round(cnt[s_] / nmo, 3), 'contrib_ex_ann_pct': round(c[s_] / nmo * 12 * 100, 2)}
                for s_ in sorted(c, key=lambda z: -c[z])}
    for rid in ('P5_SECT3_L', 'P5_SECT3_E', 'X3_SECT3BL_L', 'X3_SECT3BL_E', 'X7_SECTK1_L', 'G1_FSEL_K3_R12', 'G6_FR30_K3_R12'):
        out[f'hold_contrib_{rid}'] = contrib(rid)
    for rid in ('P5_SECT3_L', 'P5_SECT3_E', 'X3_SECT3BL_L', 'X3_SECT3BL_E'):
        if rid in runs:
            g = runs[rid][2]
            out[f'subperiods_{rid}'] = {'2007-2016': M.excess_stats(g, mkt, a=200701, z=201612),
                                        '2017-2026': M.excess_stats(g, mkt, a=201701)}
    # French 9業種から Durbl（Tesla を含む耐久財）を除いた8業種で同じ規則（事後）
    R = {'TBILL': rf}
    names = [x for x in SECT_L if x != 'FR10_Durbl']
    for x in names:
        R[x] = src[x]
    g, n, _, _, _ = run(R, mk_sector(names, 3))
    out['P5_L_without_Durbl'] = {'hold': M.excess_stats(g, mkt, a=M.HOLD_START), 'full': M.excess_stats(g, mkt)}
    # 同じ月（2000-01〜）で紙の上と実物の月次の超過の相関
    if 'P5_SECT3_L' in runs and 'P5_SECT3_E' in runs:
        gl, ge = runs['P5_SECT3_L'][2], runs['P5_SECT3_E'][2]
        ks = sorted(k for k in set(gl) & set(ge) if k in mkt)
        out['P5_L_vs_E_monthly_excess_corr'] = round(M.corr([gl[k] - mkt[k] for k in ks], [ge[k] - mkt[k] for k in ks]), 3)
        out['P5_L_minus_E_same_months'] = M.excess_stats(gl, ge, a=ks[0])
    return out


def main():
    dry = '--dry' in sys.argv
    src, rf, mkt, meta = load_all()
    log('French Mkt CAGR 全期間', round(M.cagr(mkt) * 100, 2), '2007〜', round(M.cagr(M.window(mkt, M.HOLD_START)) * 100, 2))
    if dry:
        d = dry_checks(src, meta)
        print(json.dumps(d, ensure_ascii=False, indent=0)[:20000])
        return
    sanity = dry_checks(src, meta, with_cagr=True)
    sanity['french_mkt_cagr'] = {'full': round(M.cagr(mkt) * 100, 2), 'from_2007': round(M.cagr(M.window(mkt, M.HOLD_START)) * 100, 2)}
    SRC_NAMES[:] = sorted(src)
    rows = []
    starts = {}
    runs = {}
    gcache = {}
    ref6040 = {}
    spy = {}
    for v in ('L', 'F', 'E'):
        Rv, _ = build_version(src, rf, v, ['US', 'AGG'])
        g, n, _, _, _ = run(Rv, mk_static({'US': 0.6, 'AGG': 0.4}))
        ref6040[v] = n
        spy[v] = Rv['US']
    for sp in specs():
        v = sp['version']
        R, seg = build_version(src, rf, v, sp['slots'])
        try:
            g, n, ns, wpath, trades = run(R, sp['rule_fn'], dynamic=sp.get('dynamic', False))
        except RuntimeError as e:
            log('  ✗', sp['id'], e)
            rows.append({'id': sp['id'], 'error': str(e)})
            continue
        unaligned = None
        if sp.get('align_to'):
            a0 = starts[sp['align_to']]
            unaligned = {'from': min(g), 'full': M.excess_stats(g, mkt), 'train': M.excess_stats(g, mkt, z=M.TRAIN_END),
                         'hold': M.excess_stats(g, mkt, a=M.HOLD_START), 'roll20': M.rolling(n, mkt, 20)}
            g, n, ns = ({k: v for k, v in d.items() if k >= a0} for d in (g, n, ns))
            trades = {k: v for k, v in trades.items() if k >= a0}
            wpath = {k: v for k, v in wpath.items() if madd(k, 1) >= a0}
        if len(g) < 24:
            log('  ✗', sp['id'], '月が足りない', len(g))
            rows.append({'id': sp['id'], 'family': sp['family'], 'version': v, 'error': f'月が足りない {len(g)}'})
            continue
        ks = sorted(g)
        starts[sp['id']] = ks[0]
        runs[sp['id']] = (R, wpath, g, n)
        full = M.excess_stats(g, mkt)
        train = M.excess_stats(g, mkt, z=M.TRAIN_END)
        hold = M.excess_stats(g, mkt, a=M.HOLD_START)
        recent = M.excess_stats(g, mkt, a=M.RECENT_START)
        pp = POSTPUB.get(sp['rule'])
        post = M.excess_stats(g, mkt, a=pp) if pp else None
        cost_hold = M.excess_stats(n, mkt, a=M.HOLD_START)
        cost_full = M.excess_stats(n, mkt)
        stress_hold = M.excess_stats(ns, mkt, a=M.HOLD_START)
        mk_w = {k: mkt[k] for k in ks if k in mkt}
        sh = {'train': (M.sharpe(n, rf, z=M.TRAIN_END), M.sharpe(mk_w, rf, z=M.TRAIN_END)),
              'hold': (M.sharpe(n, rf, a=M.HOLD_START), M.sharpe(mk_w, rf, a=M.HOLD_START))}
        turn_ann = round(S.mean(trades[k] for k in ks) / 2 * 12, 2)
        turn_hold = [trades[k] for k in ks if k >= M.HOLD_START]
        rep = None
        if sp['repl']:
            rep = repl_sector(rf, *sp['repl'], gcache)
        taxr = None
        if hold:
            ts = tax_sim(R, wpath, M.HOLD_START)
            if ts:
                taxr = {'after_tax_cagr': round(ts[0] * 100, 2), 'bench_after_tax_cagr': round(bh_tax(mkt, M.HOLD_START) * 100, 2),
                        'months': ts[1]}
                taxr['diff'] = round(taxr['after_tax_cagr'] - taxr['bench_after_tax_cagr'], 2)
        row = {'id': sp['id'], 'rule': sp['rule'], 'family': sp['family'], 'version': v, 'description': sp['description'],
               'timing_or_alloc': sp['timing'], 'start': ks[0], 'end': ks[-1], 'months': len(ks),
               'segments': seg, 'turnover_oneway_ann': turn_ann,
               'turnover_oneway_ann_hold': round(S.mean(turn_hold) / 2 * 12, 2) if turn_hold else None,
               'switches_per_year': round(sum(1 for k in ks if trades[k] > 0.2) / len(ks) * 12, 2),
               'full': full, 'train': train, 'hold': hold, 'recent': recent, 'postpub_from': pp, 'postpub': post,
               'cost_full': cost_full, 'cost_hold': cost_hold, 'cost_hold_stress030': stress_hold,
               'check_apply_cost_hold': M.excess_stats(M.apply_cost(g, S.mean(turn_hold) / 2 * 12 if turn_hold else 0, 0.001), mkt, a=M.HOLD_START),
               'roll20': M.rolling(n, mkt, 20), 'dca20': M.dca(n, mkt, 20),
               'sharpe': sh, 'maxdd': round(M.maxdd(n) * 100, 1), 'maxdd_bench': round(M.maxdd(mk_w) * 100, 1),
               'vs_spy_full': M.excess_stats(n, spy[v]), 'vs_spy_hold': M.excess_stats(n, spy[v], a=M.HOLD_START),
               'vs_6040_hold': M.excess_stats(n, ref6040[v], a=M.HOLD_START) if sp['alloc'] else None,
               'alloc_avg_full': summarize_alloc(wpath), 'alloc_avg_hold': summarize_alloc(wpath, M.HOLD_START),
               'last_signal': {'month': max(wpath), 'weights': {s: round(x, 3) for s, x in wpath[max(wpath)].items()}},
               'tax_jp_hold': taxr, 'repl': rep}
        if sp['family'] in ('exploratory2', 'reference2', 'exploratory3', 'reference3', 'exploratory4', 'reference4'):
            nf = {k: g[k] - 0.0075 * trades[k] / 2 for k in g}   # 売りのたびに 0.75%（短期解約手数料の最悪ケース）
            row['cost_hold_fidelity075'] = M.excess_stats(nf, mkt, a=M.HOLD_START)
            row['hold_share_by_fund'] = summarize_alloc(wpath, M.HOLD_START)
        if unaligned:
            row['unaligned_full_history_not_graded'] = unaligned
        rows.append(row)
        h = hold or {}
        ch = cost_hold or {}
        tr = train or {}
        log(f"{sp['id']:14s} {ks[0]}-{ks[-1]} train {tr.get('ex_ann')!s:>6} t{tr.get('t')!s:>5} | hold {h.get('ex_ann')!s:>6} t{h.get('t')!s:>5} "
            f"net {ch.get('ex_ann')!s:>6} cg{ch.get('cagr_diff')!s:>6} | full t{(full or {}).get('t')!s:>5} | roll {((row['roll20'] or {}).get('win_rate'))} "
            f"| turn {turn_ann} | repl {(rep or {}).get('positive')}/{(rep or {}).get('regions')}")
    # Holm と判定
    fams = {}
    for r in rows:
        if 'error' in r:
            continue
        fams.setdefault(r['family'], {})[r['id']] = (r['cost_hold'] or {}).get('p')
    hp = {f: M.holm(d) for f, d in fams.items()}
    grades = {'S': 0, 'A': 0, 'B': 0, 'C': 0}
    for r in rows:
        if 'error' in r:
            continue
        r['holm_family'] = f"{r['family']}({len(fams[r['family']])})"
        r['holm_p'] = hp[r['family']].get(r['id'])
        repl = {'regions': r['repl']['regions'], 'positive': r['repl']['positive']} if r['repl'] else None
        sp_pair = r['sharpe'] if r['timing_or_alloc'] else None
        g, c = M.grade(r['full'], r['train'], r['hold'], r['roll20'], r['cost_hold'], repl, r['holm_p'], sp_pair, r['timing_or_alloc'])
        r['grade'], r['criteria'] = g, c
        if not r['family'].startswith('reference'):
            grades[g] += 1
        log(f"  {r['id']:14s} → {g}  {''.join(k[:2] + ('✓' if v else ('-' if v is None else '✗')) + ' ' for k, v in c.items())}")
    res = {'angle': 'etf_tactical', 'prereg': PREREG, 'prereg_commit': git_sha(os.path.join('out', PREREG)),
           'global_prereg': 'mw_prereg.json',
           'benchmark': 'French Mkt（Mkt-RF+RF・総リターン）。報告: VFINX→SPY のつないだ US 枠、60/40（R1 の同じ版）',
           'cost': '売り・買いそれぞれ 0.05%（片道100%あたり 0.10%）を各月の実際の売買量に掛けてその月に引く。stress は片道 0.30%',
           'sanity': sanity, 'n_tested': len(rows), 'grades_excluding_reference': grades,
           'prereg2': 'mw_etf_tactical_prereg2.json', 'prereg2_commit': git_sha(os.path.join('out', 'mw_etf_tactical_prereg2.json')),
           'prereg3': 'mw_etf_tactical_prereg3.json', 'prereg3_commit': git_sha(os.path.join('out', 'mw_etf_tactical_prereg3.json')),
           'dead_funds_monthly_returns_from_alpha_vantage': {t: {str(k): round(v, 6) for k, v in sorted(src['AV_' + t].items())} for t in DEAD},
           'tested': rows, 'diagnostics_post_hoc_not_graded': diag_post_hoc(src, rf, mkt, runs), 'log': LOG}
    p = M.save(OUT, res)
    print('saved', p, os.path.getsize(p))


if __name__ == '__main__':
    main()
