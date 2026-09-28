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
    for t in ETFIND + RAKU:
        if t not in src:
            try:
                src[t] = yh(t)
            except Exception as e:     # 取れない ETF は対象外（0で埋めない）
                log('  ⚠ 取得失敗', t, str(e)[:80])
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
RAKU = ['AGIX', 'AIQ', 'AUAU', 'BBH', 'BBRE', 'BKCH', 'BLOK', 'BOTT', 'BOTZ', 'BUG', 'CIBR', 'CLOU', 'CNRG', 'CTEC', 'EART', 'EMLP', 'EXI', 'FAN', 'FBT', 'FDN', 'FDNI', 'FINX', 'FIW', 'FMTL', 'FRI', 'FTXL', 'FXH', 'FXL', 'FXN', 'FXZ', 'GDX', 'GDXJ', 'GNOM', 'HACK', 'HEAL', 'IBB', 'IBLC', 'ICLN', 'IFGL', 'IGF', 'ITA', 'IXC', 'IXG', 'IXJ', 'IXN', 'IYR', 'JXI', 'KROP', 'KWEB', 'KXI', 'LIT', 'MILN', 'MISL', 'MOO', 'MXI', 'NASA', 'NLR', 'OIH', 'ORBX', 'PAVE', 'PBD', 'PIO', 'PPH', 'QCLN', 'QTEC', 'REMX', 'RNRG', 'ROBO', 'ROBT', 'RTH', 'RWR', 'RXI', 'SHLD', 'SIL', 'SILJ', 'SKYY', 'SLX', 'SMH', 'SOCL', 'TAN', 'URA', 'VAW', 'VCR', 'VDC', 'VDE', 'VFH', 'VGT', 'VHT', 'VIS', 'VPU', 'WOOD', 'XLB', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLRE', 'XLU', 'XLV', 'XLY']   # 事前登録5: 楽天証券で買える業種・テーマ ETF（機械的に選んだ101本）
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
        if s.startswith('FR10_') or s.startswith('FR30_') or s.startswith('AV_') or s == 'FF_MKT' or s in FSEL or s in ETFIND or s in RAKU:
            if not src.get(s):
                continue
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


def alive_next(H, s, h=1):
    """事前登録3: t+h 月にもファンドが存在するか（合併・廃止の日付だけを見る。リターンは見ない）。事前登録4の3か月版は h=3"""
    return bool(H.R.get(s)) and max(H.R[s]) >= min(madd(H.t, h), END)   # データの終わり（END）まで存在すれば可（事前登録4の実装の不具合を直した）


def mk_sector_dyn(names, k, score='r12', min_n=20, alive=False, alive_h=1):
    """その月に12か月の窓がそろったものだけから上位 k（対象が min_n 未満の月は作らない＝始まらない）"""
    def f(H):
        sc = (lambda s: H.cum(s, 12)) if score == 'r12' else H.blend
        avail = [s for s in names if H.R.get(s) and (not alive or alive_next(H, s, alive_h)) and sc(s) is not None]
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
def run(R, rule, z=END, dynamic=False, Rh=None):
    """月末 t の信号で t+1 を持つ。戻り値: gross, net, net_stress, 重みの記録, 売買量（Σ|Δw|）
    dynamic=True（途中で消えるファンドを含む族）: 終わりは END。持つファンドは必ず翌月の値がある（規則が存在を確かめる）
    Rh（事前登録4・1日遅れ）: 信号は R（暦月）で作り、保有のリターンは Rh（t+1 月の最初の営業日→t+2 月の最初の営業日）
    規則が 'HOLD' を返した月（事前登録4・3か月ごと）は入れ替えず、値動き後の重みのまま持つ（売買0）"""
    H_ = Rh if Rh is not None else R
    if not dynamic:
        z = min([z] + [max(v) for v in H_.values() if v])     # 必要な系列のうち最も早く終わる月まで（0で埋めない）
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
        if isinstance(w, str) and w == 'HOLD':
            if not started:
                continue
            w = dict(w_prev_drift)
        if w is None:
            if started:
                raise RuntimeError(f'開始後に信号が作れない: {t}')
            continue
        if not all(nxt in H_[s] for s in w):
            if started:
                raise RuntimeError(f'開始後に保有の翌月リターンが無い: {t}→{nxt} {[s for s in w if nxt not in H_[s]]}')
            continue
        tot = sum(w.values())
        assert abs(tot - 1) < 1e-9, (t, w)
        tr = 0.0
        if started and w_prev_drift is not None:
            keys = set(w) | set(w_prev_drift)
            tr = sum(abs(w.get(s, 0) - w_prev_drift.get(s, 0)) for s in keys)
        started = True
        rp = sum(w[s] * H_[s][nxt] for s in w)
        gross[nxt] = rp
        trades[nxt] = tr
        wpath[t] = w
        w_prev_drift = {s: w[s] * (1 + H_[s][nxt]) / (1 + rp) for s in w}
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


def repl_sector(rf, k, score, absf, cache, quarterly=False):
    res, pos, n = {}, 0, 0
    for c in COUNTRIES:
        if c not in cache:
            cache[c] = (jkp_gics(c, rf), {m: v + rf[m] for m, v in M.jkp_mkt(c, 'vw').items() if m in rf})
        G, mk = cache[c]
        R = dict(G)
        R['TBILL'] = rf
        rule = gics_rule(k, score, absf)
        g, _, _, _, _ = run_loose(R, mk_quarterly(rule) if quarterly else rule, z=202512)
        st = M.excess_stats(g, mk)
        if st is None:
            res[c] = None
            continue
        n += 1
        pos += 1 if st['ex_ann'] > 0 else 0
        res[c] = {'ex_ann': st['ex_ann'], 't': st['t'], 'from': st['from'], 'to': st['to'], 'cagr_diff': st['cagr_diff']}
    return {'regions': n, 'positive': pos, 'by_country': res}


def run_loose(R, rule, z):
    """GICS 用: 開始後に一時的に信号が作れない月があっても止めない（その月は持たない＝記録しない・0で埋めない）。
    'HOLD'（3か月ごと）は前の組を値動きのまま持つ"""
    months = sorted(set().union(*[set(v) for v in R.values() if v]))
    gross, wd = {}, None
    for t in months:
        nxt = madd(t, 1)
        if nxt > z:
            break
        w = rule(Hist(R, t))
        if isinstance(w, str) and w == 'HOLD':
            w = dict(wd) if wd else None
        if w is None or not all(nxt in R[s] for s in w):
            wd = None
            continue
        rp = sum(w[s] * R[s][nxt] for s in w)
        gross[nxt] = rp
        wd = {s: w[s] * (1 + R[s][nxt]) / (1 + rp) for s in w}
    return gross, None, None, None, None


def mk_quarterly(base):
    """3・6・9・12月末だけ base で入れ替え、他の月は 'HOLD'"""
    def f(H):
        if H.t % 100 in (3, 6, 9, 12):
            return base(H)
        return 'HOLD'
    return f


# ───────────────────────── 仕様 ─────────────────────────
SRC_NAMES = []
POSTPUB = {'M1': 201101, 'M2': 201101, 'M3': 201101, 'M4': 201101, 'K1': 201101, 'K2': 201101, 'K3': 201101, 'K4': 201101, 'W1': 201101, 'W2': 201101, 'W3': 201101, 'W4': 201101, 'Q1': 201101, 'Q2': 201101, 'Q3': 201101, 'Q4': 201101, 'D1': 201101, 'D2': 201101, 'D3': 201101, 'D4': 201101, 'H1': 201101, 'H2': 201101, 'H3': 201101, 'H4': 201101, 'E1': 201101, 'E2': 201101, 'E3': 201101, 'E4': 201101, 'G1': 201101, 'G2': 201101, 'G3': 201101, 'G4': 201101, 'G6': 201101, 'G7': 201101, 'P1': 201501, 'P2': 200801, 'P3': 201801, 'P4': 201901, 'P5': 201101, 'X3': 201101, 'X4': 201101,
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
    # 第5族（事前登録4）: 3か月ごと／第6族: 1営業日遅れ
    for (k, kg, sc, lab, qid, did) in ((3, 1, 'r12', 'R12', 'Q1', 'D1'), (6, 2, 'r12', 'R12', 'Q2', 'D2'),
                                       (3, 1, 'blend', 'BL', 'Q3', 'D3'), (6, 2, 'blend', 'BL', 'Q4', 'D4')):
        one(id=f'{qid}_FSELD_K{k}_{lab}_Q', rule=qid, family='exploratory5', version='F', dynamic=True, quarterly=True,
            description=f'探索5: Fidelity Select＋合併・廃止6本の{"12か月" if sc == "r12" else "(r1+r3+r6+r12)/4"}上位{k}本・3か月ごとに入れ替え',
            rule_fn=mk_quarterly(mk_sector_dyn(fseld, k, sc, 20, alive=True, alive_h=3)), slots=fseld, repl=(kg, sc, False))
        one(id=f'{did}_FSEL_K{k}_{lab}_LAG1', rule=did, family='exploratory6', version='F', lag=True,
            description=f'探索6: Fidelity Select 33本の{"12か月" if sc == "r12" else "(r1+r3+r6+r12)/4"}上位{k}本・翌月最初の営業日の基準価額で約定',
            rule_fn=mk_sector_dyn(FSEL, k, sc, 20), slots=list(FSEL), repl=(kg, sc, False))
    # 第7族（事前登録5）: 楽天の業種・テーマ ETF／第8族: 死んだファンド＋1日遅れ（近似）
    for (k, kg, sc, lab, kid, wid) in ((3, 1, 'r12', 'R12', 'K1', 'W1'), (6, 2, 'r12', 'R12', 'K2', 'W2'),
                                       (3, 1, 'blend', 'BL', 'K3', 'W3'), (6, 2, 'blend', 'BL', 'K4', 'W4')):
        one(id=f'{kid}_RAKU_K{k}_{lab}', rule=kid, family='exploratory7', version='E', dynamic=True,
            description=f'探索7: 楽天で買える業種・テーマ ETF（101本）の{"12か月" if sc == "r12" else "(r1+r3+r6+r12)/4"}上位{k}本',
            rule_fn=mk_sector_dyn(RAKU, k, sc, 20, alive=True), slots=list(RAKU), repl=(kg, sc, False))
        one(id=f'{wid}_FSELD_K{k}_{lab}_LAG1', rule=wid, family='exploratory8', version='F', dynamic=True, lag='dead', z=202607,
            description=f'探索8: Select＋合併・廃止6本の{"12か月" if sc == "r12" else "(r1+r3+r6+r12)/4"}上位{k}本・1日遅れの約定（死んだ6本は暦月で近似）',
            rule_fn=mk_sector_dyn(fseld, k, sc, 20, alive=True), slots=fseld, repl=(kg, sc, False))
    # 第9族（事前登録6）: 月の真ん中（11営業日目）で入れ替え
    for (k, kg, sc, lab, mid) in ((3, 1, 'r12', 'R12', 'M1'), (6, 2, 'r12', 'R12', 'M2'), (3, 1, 'blend', 'BL', 'M3'), (6, 2, 'blend', 'BL', 'M4')):
        one(id=f'{mid}_FSEL_K{k}_{lab}_MID', rule=mid, family='exploratory9', version='F', lag='mid',
            description=f'探索9: Fidelity Select 33本の{"12か月" if sc == "r12" else "(r1+r3+r6+r12)/4"}上位{k}本・月の11営業日目で区切って毎月入れ替え',
            rule_fn=mk_sector_dyn(FSEL, k, sc, 20), slots=list(FSEL), repl=(kg, sc, False))
    one(id='K5_RAKU_EW', rule='K5', family='reference7', version='E', dynamic=True, description='参照7: 楽天の業種・テーマ ETF を全部等分',
        rule_fn=mk_ew_dyn(RAKU, 20, alive=True), slots=list(RAKU), repl=None)
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


def build_lag(names, k=1):
    """事前登録4: 1営業日遅れの保有区間。区間 m = m 月の最初の営業日の引け → m+1 月の最初の営業日の引け（French 日次の暦）。
    事前登録6: k=11 で『月の11営業日目』で区切ったずらした月。
    戻り値: Rh {ファンド: {m: 区間リターン}}, 市場 {m: 区間リターン}, RF {m: 区間の複利}"""
    ffd = M.ff_factors('daily')
    mk_d, rf_d = ffd['mkt'], ffd['rf']
    days = sorted(d for d in mk_d if d in rf_d)
    bym = {}
    for d in days:
        bym.setdefault(d // 100, []).append(d)
    first = {m: v[k - 1] for m, v in bym.items() if len(v) >= k}
    pos = {d: i for i, d in enumerate(days)}
    mkt_lag, rf_lag = {}, {}
    for m in sorted(first):
        m2 = madd(m, 1)
        if m2 not in first:
            continue
        v = w = 1.0
        for d in days[pos[first[m]] + 1:pos[first[m2]] + 1]:
            v *= 1 + mk_d[d]
            w *= 1 + rf_d[d]
        mkt_lag[m], rf_lag[m] = v - 1, w - 1
    import bisect
    Rh = {}
    for t in names:
        dr = M.yahoo(t, interval='1d')
        ks = sorted(dr)
        lv, L = [], 1.0
        for k in ks:
            L *= 1 + dr[k]
            lv.append(L)

        def level(d):
            i = bisect.bisect_right(ks, d) - 1
            if i < 0:
                return None
            dd = ks[i]
            gap = (datetime.date(d // 10000, d // 100 % 100, d % 100) - datetime.date(dd // 10000, dd // 100 % 100, dd % 100)).days
            return lv[i] if gap <= 5 else None     # 5日より古い値は使わない（0で埋めない）

        out = {}
        for m in mkt_lag:
            a0, b0 = level(first[m]), level(first[madd(m, 1)])
            if a0 and b0 and first[m] > ks[0]:
                out[m] = b0 / a0 - 1
        Rh[t] = out
    return Rh, mkt_lag, rf_lag


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
    # 第2〜8族の S の中身（事後）: 年ごとの超過・ファンド別の寄与・一番効いたファンドを除く・現実的な短期手数料・区間
    for rid in ('H3_FSELD_K3_BL', 'W3_FSELD_K3_BL_LAG1', 'G3_FSEL_K3_BL', 'D3_FSEL_K3_BL_LAG1', 'K1_RAKU_K3_R12'):
        if rid not in runs:
            continue
        R_, wp_, g_, n_ = runs[rid]
        bm = runs.get('__bench__' + rid) or mkt
        yrs = {}
        for m in sorted(n_):
            if m in bm:
                a_, b_ = yrs.get(m // 100, (1.0, 1.0))
                yrs[m // 100] = (a_ * (1 + n_[m]), b_ * (1 + bm[m]))
        out[f'yearly_excess_net_{rid}'] = {y: round((a_ - b_) * 100, 1) for y, (a_, b_) in yrs.items()}
        hold_years = [v for y, v in out[f'yearly_excess_net_{rid}'].items() if y >= 2007]
        out[f'yearly_win_share_2007on_{rid}'] = round(sum(1 for v in hold_years if v > 0) / len(hold_years), 3) if hold_years else None
        out[f'hold_contrib_{rid}'] = contrib(rid) if not rid.startswith(('W', 'D')) else None
        out[f'subperiods_{rid}'] = {'2007-2016': M.excess_stats(n_, bm, a=200701, z=201612), '2017-': M.excess_stats(n_, bm, a=201701)}
    # 一番効いたファンドを除いた H3（事後）
    if 'H3_FSELD_K3_BL' in runs:
        cb = contrib('H3_FSELD_K3_BL')
        top = next(iter(cb))
        names = [x for x in list(FSEL) + ['AV_' + t for t in DEAD] if x != top]
        R2 = {'TBILL': rf}
        for x in names:
            if src.get(x):
                R2[x] = src[x]
        g2, n2, _, _, _ = run(R2, mk_sector_dyn(names, 3, 'blend', 20, alive=True), dynamic=True)
        out['H3_without_top_contributor'] = {'removed': top, 'hold': M.excess_stats(n2, mkt, a=M.HOLD_START), 'full': M.excess_stats(n2, mkt),
                                             'train': M.excess_stats(n2, mkt, z=M.TRAIN_END)}
        # 現実的な短期手数料: 保有の月（前月の最後の営業日→当月の最後の営業日）が30日未満の月の売りにだけ 0.75%
        ffd = M.ff_factors('daily')
        last = {}
        for d in sorted(ffd['mkt']):
            last[d // 100] = d
        short = set()
        for m in last:
            pm = madd(m, -1)
            if pm in last:
                a_, b_ = last[pm], last[m]
                days = (datetime.date(b_ // 10000, b_ // 100 % 100, b_ % 100) - datetime.date(a_ // 10000, a_ // 100 % 100, a_ % 100)).days
                if days < 30:
                    short.add(madd(m, 1))    # m 月末に売る → その売買の費用は m+1 月に計上（run と同じ）
        R_, wp_, g_, n_ = runs['H3_FSELD_K3_BL']
        tr_ = {madd(t, 1): None for t in wp_}
        # 売買量は run の記録から作り直す（n_ = g_ − 0.05%×売買量）
        nf = {}
        for m in g_:
            trade = (g_[m] - n_[m]) / C_SIDE if C_SIDE else 0
            nf[m] = n_[m] - (0.0075 * trade / 2 if m in short else 0.0)
        out['H3_realistic_fidelity_fee'] = {'rule': '保有月が30日未満（前月末→当月末の営業日）の月の売りにだけ 0.75%（全部の売りに掛ける最悪ケースより現実的・事後）',
                                            'short_months_share': round(sum(1 for m in g_ if m in short) / len(g_), 3),
                                            'hold': M.excess_stats(nf, mkt, a=M.HOLD_START), 'full': M.excess_stats(nf, mkt)}
        # 生き残りの偏りの大きさ: 生き残りだけの等分の超過を 1987-1999 と 2000-2006 で
        if 'G5_FSEL_EW' in runs:
            ge = runs['G5_FSEL_EW'][2]
            out['survivor_EW_excess_by_era'] = {'1987-1999': M.excess_stats(ge, mkt, z=199912), '2000-2006': M.excess_stats(ge, mkt, a=200001, z=200612),
                                                '2007-': M.excess_stats(ge, mkt, a=200701)}
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


DEVIATIONS = [
    '判定の保有期間は全角度共通の mw_prereg（2007-01〜）。課題文は公表後を主の保有期間と書くが、事前登録どおり公表後（GEM 2015〜・GTAA 2008〜・VAA 2018〜・DAA 2019〜・セクター 2011〜）は並べて報告（postpub）',
    '費用は mw_common.apply_cost と同じ単価（片道100%あたり 0.10%＝売り・買いそれぞれ 0.05%）を、平均でなく各月の実際の売買量に掛けた。apply_cost で平均化した版を check_apply_cost_hold に併記（差はほぼ無い）',
    'Faber の10か月線は価格指数でなく総リターン指数で判定（投信の分配落ちで偽の信号が出ないため・事前登録どおり）。DAA の守りの UST（2倍の国債 ETF）は LQD に置き換え（事前登録どおり）',
    'Yahoo は投信の月次を 1985-02 より前に返さない（日次はもっと前まである）。F 版の訓練期間はそこで切れる',
    '事前登録3の死んだ Select 6本（FSESX・FSNGX・FSAIX・FSDCX・FCYIX・FSCGX）は Alpha Vantage（MCP）の月次の調整後終値を手で写した（1999-12〜各ファンドの最後の月）。全行で『分配の無い月は 調整後÷終値 が前月と同じ』を確かめ崩れ0。AV と Yahoo は生きている FSENX で累積リターンの差が数年で最大2%ほど（AV が低い側）。再現のため月次リターンを dead_funds_monthly_returns_from_alpha_vantage に同梱',
    '事前登録4の3か月版で『3か月先まで存在』をデータの終わり（2026-08）の先まで求めて最後の四半期に全ファンドが対象外になる実装の不具合があった → 『3か月先かデータの終わりまで存在』に直した（Q 族の結果を見る前・規則の意図どおり）',
    '事前登録5の第8族（死んだファンド＋1日遅れ）は死んだ6本の区間に暦月のリターンを使う近似（事前登録どおり）',
    'mw_common に不具合は見つからなかった（yahoo() の月次は日次から作った月末リターンと4本で完全一致を確認）',
    'C5 はセクター規則だけ JKP GICS 11セクター（7か国・1999-07〜2025-12）。9セクター・約32業種の規則を11セクターで当てる（K=3→上位1・K=6→上位2 は業種数に対する割合で事前に固定）。他の規則は地域版が無く N/A',
    '参照族（reference*）は判定するが勝ちの候補に数えない（grades_excluding_reference）',
]
SUMMARY_JA = [
    '公表された戦術的配分（GEM・GTAA-5・VAA・DAA）は、ETF・投信の実物でも長い代理でも 2007年以降は市場に年2.5〜6.4%負けた（全部 C）。下落は浅い（最大下落 −11〜−20% 対 市場 −50%）が、勝ちの線はシャープではなくリターンで超える必要がある',
    '9つの SPDR セクターの勢い（上位3）は 2007年以降 −0.2%/年（C）。同じ規則を French の9業種（紙の上）に当てると +2.5%/年（A）だが、その保有期間の勝ちは耐久財（Tesla）1業種が主で、除くと +0.7%/年',
    'NASDAQ100 と S&P500 の強い方への切替は 2007年以降 +4.3%/年（t3.4）だが、1986〜2006 の訓練期間で t0.7 しかなく C（勝ちは巨大テックの時代＝後知恵）',
    '細かい業種の実在ファンド（Fidelity Select 約33本・1987〜）で (r1+r3+r6+r12)/4 の上位3を毎月持つ規則が S: 2007年以降 +5.6%/年（t2.4）・費用後 +5.2',
    'その S を疑った: 合併・廃止の6本を足す +4.4（t1.9・S のまま）、翌営業日の約定 +5.1（S）、両方同時 +4.5（t1.95・S）。しかし3か月ごとの入れ替えだと −1.7%/年（勝ちは毎月の鮮度に依存）、Fidelity の30日未満の解約手数料 0.75% を現実的に当てると +2.9%/年・t1.25（B 相当）',
    '日本の居住者は Fidelity Select（米国籍の投信）を買えない。楽天で買える業種・テーマ ETF 101本で同じ型（12か月上位3）は 2007年以降 年+7.5%（算術・t1.7）・年率差+3.7% だが、2003〜2006 しか訓練期間が無く C。値動きが非常に荒い（2020 +59%・2021 −39%）',
]


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
    lagd = midd = None
    for sp in specs():
        v = sp['version']
        if sp.get('lag') and sp['lag'] != 'mid':
            if lagd is None:
                lagd = build_lag(FSEL)
            Rh, mkt_, rf_ = lagd
            if sp['lag'] == 'dead':                         # 事前登録5: 死んだ6本は暦月のリターンで近似
                Rh = dict(Rh)
                for t_ in DEAD:
                    Rh['AV_' + t_] = src['AV_' + t_]
        else:
            Rh, mkt_, rf_ = None, mkt, rf
        if sp.get('lag') == 'mid':                          # 事前登録6: 月の11営業日目で区切ったずらした月（信号も保有も）
            if midd is None:
                midd = build_lag(FSEL, k=11)
            Rm, mkt_, rf_ = midd
            R = {'TBILL': rf_}
            R.update({x: Rm[x] for x in FSEL if Rm.get(x)})
            seg, Rh = {}, None
        else:
            R, seg = build_version(src, rf, v, sp['slots'])
        try:
            g, n, ns, wpath, trades = run(R, sp['rule_fn'], z=sp.get('z', END), dynamic=sp.get('dynamic', False), Rh=Rh)
        except RuntimeError as e:
            log('  ✗', sp['id'], e)
            rows.append({'id': sp['id'], 'error': str(e)})
            continue
        unaligned = None
        if sp.get('align_to'):
            a0 = starts[sp['align_to']]
            unaligned = {'from': min(g), 'full': M.excess_stats(g, mkt_), 'train': M.excess_stats(g, mkt_, z=M.TRAIN_END),
                         'hold': M.excess_stats(g, mkt_, a=M.HOLD_START), 'roll20': M.rolling(n, mkt_, 20)}
            g, n, ns = ({k: v for k, v in d.items() if k >= a0} for d in (g, n, ns))
            trades = {k: v for k, v in trades.items() if k >= a0}
            wpath = {k: v for k, v in wpath.items() if madd(k, 1) >= a0}
        if len(g) < 24:
            log('  ✗', sp['id'], '月が足りない', len(g))
            rows.append({'id': sp['id'], 'family': sp['family'], 'version': v, 'error': f'月が足りない {len(g)}'})
            continue
        ks = sorted(g)
        starts[sp['id']] = ks[0]
        runs[sp['id']] = (Rh if Rh is not None else R, wpath, g, n)
        if sp.get('lag'):
            runs['__bench__' + sp['id']] = mkt_
        full = M.excess_stats(g, mkt_)
        train = M.excess_stats(g, mkt_, z=M.TRAIN_END)
        hold = M.excess_stats(g, mkt_, a=M.HOLD_START)
        recent = M.excess_stats(g, mkt_, a=M.RECENT_START)
        pp = POSTPUB.get(sp['rule'])
        post = M.excess_stats(g, mkt_, a=pp) if pp else None
        cost_hold = M.excess_stats(n, mkt_, a=M.HOLD_START)
        cost_full = M.excess_stats(n, mkt_)
        stress_hold = M.excess_stats(ns, mkt_, a=M.HOLD_START)
        mk_w = {k: mkt_[k] for k in ks if k in mkt_}
        sh = {'train': (M.sharpe(n, rf_, z=M.TRAIN_END), M.sharpe(mk_w, rf_, z=M.TRAIN_END)),
              'hold': (M.sharpe(n, rf_, a=M.HOLD_START), M.sharpe(mk_w, rf_, a=M.HOLD_START))}
        turn_ann = round(S.mean(trades[k] for k in ks) / 2 * 12, 2)
        turn_hold = [trades[k] for k in ks if k >= M.HOLD_START]
        rep = None
        if sp['repl']:
            rep = repl_sector(rf, *sp['repl'], gcache, quarterly=sp.get('quarterly', False))
        taxr = None
        if hold:
            ts = tax_sim(Rh if Rh is not None else R, wpath, M.HOLD_START)
            if ts:
                taxr = {'after_tax_cagr': round(ts[0] * 100, 2), 'bench_after_tax_cagr': round(bh_tax(mkt_, M.HOLD_START) * 100, 2),
                        'months': ts[1]}
                taxr['diff'] = round(taxr['after_tax_cagr'] - taxr['bench_after_tax_cagr'], 2)
        row = {'id': sp['id'], 'rule': sp['rule'], 'family': sp['family'], 'version': v, 'description': sp['description'],
               'timing_or_alloc': sp['timing'], 'start': ks[0], 'end': ks[-1], 'months': len(ks),
               'segments': seg, 'turnover_oneway_ann': turn_ann,
               'turnover_oneway_ann_hold': round(S.mean(turn_hold) / 2 * 12, 2) if turn_hold else None,
               'switches_per_year': round(sum(1 for k in ks if trades[k] > 0.2) / len(ks) * 12, 2),
               'full': full, 'train': train, 'hold': hold, 'recent': recent, 'postpub_from': pp, 'postpub': post,
               'cost_full': cost_full, 'cost_hold': cost_hold, 'cost_hold_stress030': stress_hold,
               'check_apply_cost_hold': M.excess_stats(M.apply_cost(g, S.mean(turn_hold) / 2 * 12 if turn_hold else 0, 0.001), mkt_, a=M.HOLD_START),
               'roll20': M.rolling(n, mkt_, 20), 'dca20': M.dca(n, mkt_, 20),
               'sharpe': sh, 'maxdd': round(M.maxdd(n) * 100, 1), 'maxdd_bench': round(M.maxdd(mk_w) * 100, 1),
               'vs_spy_full': None if sp.get('lag') else M.excess_stats(n, spy[v]), 'vs_spy_hold': None if sp.get('lag') else M.excess_stats(n, spy[v], a=M.HOLD_START),
               'vs_6040_hold': M.excess_stats(n, ref6040[v], a=M.HOLD_START) if sp['alloc'] else None,
               'alloc_avg_full': summarize_alloc(wpath), 'alloc_avg_hold': summarize_alloc(wpath, M.HOLD_START),
               'last_signal': {'month': max(wpath), 'weights': {s: round(x, 3) for s, x in wpath[max(wpath)].items()}},
               'tax_jp_hold': taxr, 'repl': rep}
        if sp['family'] in ('exploratory2', 'reference2', 'exploratory3', 'reference3', 'exploratory4', 'reference4', 'exploratory5', 'exploratory6',
                            'exploratory7', 'reference7', 'exploratory8', 'exploratory9'):
            nf = {k: g[k] - 0.0075 * trades[k] / 2 for k in g}   # 売りのたびに 0.75%（短期解約手数料の最悪ケース）
            row['cost_hold_fidelity075'] = M.excess_stats(nf, mkt_, a=M.HOLD_START)
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
           'deviations': DEVIATIONS, 'summary_ja': SUMMARY_JA,
           'prereg2': 'mw_etf_tactical_prereg2.json', 'prereg2_commit': git_sha(os.path.join('out', 'mw_etf_tactical_prereg2.json')),
           'prereg6': 'mw_etf_tactical_prereg6.json', 'prereg6_commit': git_sha(os.path.join('out', 'mw_etf_tactical_prereg6.json')),
           'prereg5': 'mw_etf_tactical_prereg5.json', 'prereg5_commit': git_sha(os.path.join('out', 'mw_etf_tactical_prereg5.json')),
           'prereg4': 'mw_etf_tactical_prereg4.json', 'prereg4_commit': git_sha(os.path.join('out', 'mw_etf_tactical_prereg4.json')),
           'prereg3': 'mw_etf_tactical_prereg3.json', 'prereg3_commit': git_sha(os.path.join('out', 'mw_etf_tactical_prereg3.json')),
           'dead_funds_monthly_returns_from_alpha_vantage': {t: {str(k): round(v, 6) for k, v in sorted(src['AV_' + t].items())} for t in DEAD},
           'tested': rows, 'diagnostics_post_hoc_not_graded': diag_post_hoc(src, rf, mkt, runs), 'log': LOG}
    p = M.save(OUT, res)
    print('saved', p, os.path.getsize(p))


if __name__ == '__main__':
    main()
