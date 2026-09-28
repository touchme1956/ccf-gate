#!/usr/bin/env python3
"""night/mw_valdca.py — 『市場に勝てる歴史検証』角度 valdca: 割安さで配分を変える規則と、毎月積立の『工夫』（読むだけ・門の判定には不使用）

事前登録: out/mw_valdca_prereg.json（規則・線は測る前に固定。ここで動かさない）
出力    : out/mw_valdca.json

族
- P（主・格付け）: 割安さ（CAPE・超過CAPE利回り ECY・益回り）で株と10年国債（または短期金利）の割合を毎月決める規則。
  米国（French Mkt 1926-07〜2026-08）で格付けし、米国外20か国（French の国別データ＋World Bank の物価＋OECD の金利）で再現を見る（C5）。
- K（積立の工夫・格付け外の D判定）: 押し目買い（現金を貯めて下げたら入れる）・10か月線の下で倍額・バリュー平均法（Edleson 1991）・
  割安さで積立額を増減・割安さで積立先を切替・一括 vs 分割。相手は『毎月同額を市場へそのまま』。20年窓の最終額で比べる。

約束: 月次リターンは小数。総リターンどうしで比べる。欠測を0で埋めない（欠けた月は捨てるか、その国・窓を外す）。
      信号は月末 t に分かる値だけで作り、t+1 月のリターンに当てる。利益は3か月遅れ（決算の発表の遅れ）で使う。
"""
import io, json, math, os, re, subprocess, sys, zipfile, datetime, statistics as S

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402

PREREG = 'mw_valdca_prereg.json'
OUT = 'mw_valdca.json'
END_M = 202608                     # French の終わり
COST_UNIT = 0.001                  # 片道 100% あたり 0.10%（大型株・国債ETF）
SPREAD_MARGIN = 0.015              # 借入 = 短期金利 + 1.5%/年
E_LAG = 3                          # 利益は3か月遅れで使う
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


def ym_add(k, n):
    y, m = divmod(k, 100)
    t = y * 12 + (m - 1) + n
    return (t // 12) * 100 + t % 12 + 1


def months(a, z):
    out, k = [], a
    while k <= z:
        out.append(k)
        k = ym_add(k, 1)
    return out


# ───────────────────────── 米国のデータ ─────────────────────────
def fred(sid, max_age=30):
    b = M.get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=' + sid, f'fred_{sid}.csv', max_age_days=max_age).decode()
    out = {}
    for ln in b.strip().splitlines()[1:]:
        d, v = ln.split(',')[:2]
        if v in ('', '.'):
            continue
        out[d] = float(v)
    return out


def fred_monthly(sid):
    return {int(d[:4]) * 100 + int(d[5:7]): v for d, v in fred(sid).items()}


def shiller():
    """Shiller ie_data.xls → dict 列名: {yyyymm: 値}。P（月中平均）・D・E・CPI・GS10・CAPE・ECY・債券の総リターン（行 t = t→t+1 の月）"""
    import xlrd
    b = M.get('http://www.econ.yale.edu/~shiller/data/ie_data.xls', 'shiller_ie_data.xls', max_age_days=60)
    sh = xlrd.open_workbook(file_contents=b).sheet_by_name('Data')
    cols = {'P': 1, 'D': 2, 'E': 3, 'CPI': 4, 'GS10': 6, 'CAPE': 12, 'TRCAPE': 14, 'ECY': 16, 'BOND': 17}
    out = {c: {} for c in cols}
    for i in range(8, sh.nrows):
        row = sh.row_values(i)
        d = row[0]
        if not isinstance(d, float):
            continue
        y = int(d)
        m = int(round((d - y) * 100))
        k = y * 100 + m
        for c, j in cols.items():
            v = row[j]
            if isinstance(v, float):
                out[c][k] = v
    return out


def goyal():
    import openpyxl
    b = M.get('https://docs.google.com/spreadsheets/d/17mw_IpaiLFDrGnrPRQ2o1ugV5nJsZuD1/export?format=xlsx',
              'goyal_predictors_2025.xlsx', max_age_days=60)
    wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
    rows = list(wb['Monthly'].iter_rows(values_only=True))
    h = list(rows[0])
    want = ['price', 'e12', 'd12', 'ltr', 'Rfree', 'lty']
    idx = {w: h.index(w) for w in want}
    out = {w: {} for w in want}
    for r in rows[1:]:
        if r[0] is None:
            continue
        k = int(r[0])
        for w, i in idx.items():
            if r[i] is not None:
                out[w][k] = float(r[i])
    return out


def multpl(slug):
    """multpl.com の月次表（新しい順）→ {yyyymm: 値}"""
    t = M.get(f'https://www.multpl.com/{slug}/table/by-month', f'multpl_{slug}.html', max_age_days=5).decode('utf-8', 'replace')
    mon = {m: i + 1 for i, m in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'])}
    out = {}
    for a, b in re.findall(r'<tr[^>]*>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>', t, re.S):
        a = a.strip()
        mm = re.match(r'([A-Z][a-z]{2}) (\d+), (\d{4})', a)
        if not mm:
            continue
        v = re.sub('<[^>]+>', '', b).replace('&#x2002;', '').replace(',', '').strip()
        try:
            v = float(v)
        except ValueError:
            continue
        k = int(mm.group(3)) * 100 + mon[mm.group(1)]
        out.setdefault(k, v)  # 同じ月に2行（月初と最新日）あれば新しい方（表の先頭側）を採る
    return out


def gspc_monthly_avg():
    """Yahoo ^GSPC 日次終値の月中平均（Shiller の P と同じ定義）→ {yyyymm: 値}"""
    u = 'https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?period1=-1400000000&period2=1790000000&interval=1d'
    j = json.loads(M.get(u, 'valdca_yh_GSPC_1d.json', max_age_days=3650))
    r = j['chart']['result'][0]
    acc = {}
    for t, c in zip(r['timestamp'], r['indicators']['quote'][0]['close']):
        if c is None:
            continue
        d = datetime.datetime.utcfromtimestamp(t)
        acc.setdefault(d.year * 100 + d.month, []).append(c)
    return {k: sum(v) / len(v) for k, v in acc.items()}


def dgs10_month_end():
    d = fred('DGS10')
    out = {}
    for k in sorted(d):
        out[int(k[:4]) * 100 + int(k[5:7])] = d[k]  # 月の最後の営業日で上書き
    return out


def par_bond_ret(y0, y1, n_years=10.0):
    """利回り y0（年率・小数）で買った n 年の額面債を1か月後に y1 で売る総リターン（Shiller の作り方と同じ・年1回利払いの近似）"""
    T = n_years - 1 / 12
    if y1 <= 0:
        y1 = 1e-6
    price = (y0 / y1) * (1 - (1 + y1) ** (-T)) + (1 + y1) ** (-T)
    return price - 1 + y0 / 12


def us_data():
    """米国: 株（French Mkt）・RF・10年国債・信号（CAPE・ECY・益回り）を作る"""
    ff = M.ff_factors('monthly')
    mkt = {k: v for k, v in ff['mkt'].items() if k <= END_M}
    rf = {k: v for k, v in ff['rf'].items() if k <= END_M}
    sh = shiller()
    gy = goyal()
    cpi_f = fred_monthly('CPIAUCNS')
    gs10_f = fred_monthly('GS10')
    # 物価: 1913-01〜 FRED CPIAUCNS、それより前は Shiller
    cpi = {k: v for k, v in sh['CPI'].items() if k < 191301}
    cpi.update(cpi_f)
    # 10年金利（月中平均）: 1953-04〜 FRED GS10、それより前は Shiller の長期金利
    gs10 = {k: v for k, v in sh['GS10'].items() if k < 195304}
    gs10.update(gs10_f)
    # 株価（月中平均）: Shiller P（〜2023-09）＋ Yahoo ^GSPC 日次の月中平均（2023-10〜）
    P = dict(sh['P'])
    gav = gspc_monthly_avg()
    for k, v in gav.items():
        if k > max(P) and k <= END_M:
            P[k] = v
    # 利益（12か月・名目）: Shiller E（〜2023-06）＋ Goyal-Welch e12（2023-07〜2025-12）＋ multpl の実質利益を名目へ（2026-01〜）
    E = dict(sh['E'])
    for k, v in gy['e12'].items():
        if k > max(E):
            E[k] = v
    mre = multpl('s-p-500-earnings')  # 実質（直近の物価で表示）
    ov = [k for k in mre if k in E and k in cpi and k >= 202301 and k <= 202512]
    scale = S.median([E[k] / cpi[k] / mre[k] for k in ov]) if ov else None
    ext_e = {}
    if scale:
        for k, v in mre.items():
            if k > max(E) and k in cpi:
                ext_e[k] = v * scale * cpi[k]
            elif k > max(E) and k not in cpi:
                # その月の物価がまだ無い（公表前）→ 使わない（欠測を埋めない）
                pass
        E.update(ext_e)
    # 10年国債の総リターン（t 月 = t-1 月末→t 月末）
    bond = {}
    for k in months(192607, 196112):
        if k in gy['ltr']:
            bond[k] = gy['ltr'][k]
    me = dgs10_month_end()
    for k in months(196202, END_M):
        a = ym_add(k, -1)
        if a in me and k in me:
            bond[k] = par_bond_ret(me[a] / 100, me[k] / 100)
    # 1962-01 は 1961-12 の月末利回りが無いので Goyal ltr で埋めずに GS10 月中平均から（1か月だけ・明記）
    if 196201 not in bond and 196112 in gs10 and 196201 in gs10:
        bond[196201] = par_bond_ret(gs10[196112] / 100, gs10[196201] / 100)
    sig = us_signals(P, E, cpi, gs10)
    meta = {'E_ext_scale_months': len(ov), 'E_ext_months': sorted(ext_e), 'P_ext_from': min(k for k in P if k > 202309) if any(k > 202309 for k in P) else None}
    return {'mkt': mkt, 'rf': rf, 'bond': bond, 'sig': sig, 'sh': sh, 'gy': gy, 'cpi': cpi, 'gs10': gs10, 'P': P, 'E': E, 'meta': meta}


def carry(d, lo=187101, hi=END_M):
    """公表されなかった月（2025-10 の米CPI＝政府閉鎖）を『その時点で分かっていた最新の値』で読む。0 では埋めない"""
    out, last = {}, None
    for k in months(lo, hi):
        if k in d:
            last = d[k]
        if last is not None:
            out[k] = last if k not in d else d[k]
    return out


def us_signals(P, E, cpi, gs10, lag=E_LAG):
    """月末 t に分かる値で作る信号: CAPE（価格は t-1 の物価で実質化・利益は t-lag〜t-lag-119 の実質の平均）、ECY、益回り（12か月）"""
    out = {'CAPE': {}, 'ECY': {}, 'EY1': {}, 'RY': {}, 'CAPE0': {}}
    ks = sorted(P)
    cpi = carry(cpi)
    for t in ks:
        c1 = cpi.get(ym_add(t, -1))
        if c1 is None:
            continue
        el = [ym_add(t, -lag - i) for i in range(120)]
        if any(k not in E or k not in cpi for k in el):
            continue
        e10 = sum(E[k] / cpi[k] for k in el) / 120
        if e10 <= 0:
            continue
        cape = (P[t] / c1) / e10
        out['CAPE'][t] = cape
        ek = ym_add(t, -lag)
        out['EY1'][t] = E[ek] / P[t]
        c121 = cpi.get(ym_add(t, -121))
        if t in gs10 and c121:
            pi10 = (c1 / c121) ** (1 / 10) - 1
            ry = gs10[t] / 100 - pi10
            out['RY'][t] = ry
            out['ECY'][t] = 1 / cape - ry
        # 遅れなし（Shiller の列との照合用・判定には使わない）
        el0 = [ym_add(t, -i) for i in range(120)]
        if t in cpi and all(k in E and k in cpi for k in el0):
            out['CAPE0'][t] = (P[t] / cpi[t]) / (sum(E[k] / cpi[k] for k in el0) / 120)
    return out


# ───────────────────────── 米国外（French の国別＋World Bank の物価＋OECD の金利） ─────────────────────────
COUNTRIES = {  # French のファイル名: (ISO2, ISO3, 表示名)
    'UK.Dat': ('GB', 'GBR', '英国'), 'Austria.Dat': ('AT', 'AUT', 'オーストリア'), 'Austrlia.Dat': ('AU', 'AUS', '豪州'),
    'Belgium.Dat': ('BE', 'BEL', 'ベルギー'), 'Canada.Dat': ('CA', 'CAN', 'カナダ'), 'Denmark.Dat': ('DK', 'DNK', 'デンマーク'),
    'Finland.Dat': ('FI', 'FIN', 'フィンランド'), 'France.Dat': ('FR', 'FRA', 'フランス'), 'Germany.Dat': ('DE', 'DEU', 'ドイツ'),
    'Ireland.Dat': ('IE', 'IRL', 'アイルランド'), 'Italy.Dat': ('IT', 'ITA', 'イタリア'), 'Japan.Dat': ('JP', 'JPN', '日本'),
    'Nethrlnd.Dat': ('NL', 'NLD', 'オランダ'), 'NewZland.Dat': ('NZ', 'NZL', 'ニュージーランド'), 'Norway.Dat': ('NO', 'NOR', 'ノルウェー'),
    'Spain.Dat': ('ES', 'ESP', 'スペイン'), 'Sweden.Dat': ('SE', 'SWE', 'スウェーデン'), 'Swtzrlnd.Dat': ('CH', 'CHE', 'スイス'),
}
# 香港・シンガポール（OECD の金利が無い）とマレーシア（1994-2001 のみ）は使わない＝事前登録で固定


def _blocks(lines):
    out, cur = [], None
    for l in lines:
        s = l.strip()
        if re.match(r'^\d{4,6}\s', s):
            if cur is not None:
                cur['rows'].append(s.split())
            continue
        if s == '':
            if cur is not None and cur['rows']:
                out.append(cur)
                cur = None
            continue
        if cur is None or cur['rows']:
            if cur is not None and cur['rows']:
                out.append(cur)
            cur = {'hdr': [s], 'rows': []}
        else:
            cur['hdr'].append(s)
    if cur and cur['rows']:
        out.append(cur)
    return out


def french_countries():
    """→ {ファイル名: {'loc': {yyyymm: 総リターン(現地通貨)}, 'usd': {...}, 'ann': {年: {'EP','Yld','BM'}}}}"""
    z = zipfile.ZipFile(io.BytesIO(M.get(M.FR.format('F-F_International_Countries'), name='fr_F-F_International_Countries.zip')))
    out = {}
    for n in z.namelist():
        if n not in COUNTRIES:
            continue
        bl = _blocks(z.read(n).decode('latin-1').splitlines())
        assert 'Dollar' in bl[0]['hdr'][0] and 'Local' in bl[1]['hdr'][0] and 'Not Reqd' in bl[1]['hdr'][0], n
        assert 'Average of Annual' in bl[8]['hdr'][0] and 'Not Reqd' in bl[8]['hdr'][2], n
        loc = {int(r[0]): float(r[1]) / 100 for r in bl[1]['rows'] if float(r[1]) > -99}
        usd = {int(r[0]): float(r[1]) / 100 for r in bl[0]['rows'] if float(r[1]) > -99}
        ann = {}
        for r in bl[8]['rows']:
            bm, ep, yld = float(r[2]), float(r[3]), float(r[5])
            ann[int(r[0])] = {'BM': bm / 100 if bm > -99 else None, 'EP': ep / 100 if ep > -99 else None, 'Yld': yld / 100 if yld > -99 else None}
        out[n] = {'loc': loc, 'usd': usd, 'ann': ann}
    return out


def wb_cpi():
    iso3 = ';'.join(v[1] for v in COUNTRIES.values())
    b = M.get(f'https://api.worldbank.org/v2/country/{iso3}/indicator/FP.CPI.TOTL?format=json&per_page=2000&date=1955:2026',
              'wb_cpi_valdca.json', max_age_days=30)
    j = json.loads(b)
    out = {}
    for r in j[1]:
        if r['value'] is None:
            continue
        out.setdefault(r['countryiso3code'], {})[int(r['date'])] = float(r['value'])
    return out


def country_data(fname, cpi_all):
    """1か国ぶん: 株（現地通貨の総リターン）・現金・10年国債・信号（CAPE・ECY・益回り）。欠けは埋めない"""
    iso2, iso3, jp = COUNTRIES[fname]
    fc = french_countries()[fname]
    tr, ann = fc['loc'], fc['ann']
    cpi = cpi_all.get(iso3, {})
    y10 = fred_monthly(f'IRLTLT01{iso2}M156N')
    r3 = fred_monthly(f'IR3TIB01{iso2}M156N')
    rc = fred_monthly(f'IRSTCI01{iso2}M156N')
    cash_rate = {}
    for k in set(r3) | set(rc):
        cash_rate[k] = r3[k] if k in r3 else rc[k]
    ks = sorted(tr)
    # 配当を除いた価格指数（月の配当 = その時点で分かる配当利回り÷12 の近似）
    def known_year(k, lag_m=6):
        y, m = divmod(k, 100)
        return y if m > lag_m else y - 1    # 年 Y の比率（Y-1 年末の値・Y-1 期の決算）は Y 年7月から使う
    PI, lv = {}, 1.0
    first = ks[0]
    PI[ym_add(first, -1)] = 1.0
    for k in ks:
        a = ann.get(known_year(k))
        if a is None or a['Yld'] is None:
            a = ann.get(k // 100)  # 最初の半年だけは同じ年の値（配当を除く近似のため・信号には使わない）
        dy = (a['Yld'] if a and a['Yld'] is not None else 0.0) / 12
        lv *= (1 + tr[k]) / (1 + dy)
        PI[k] = lv
    # 決算期 Y-1 の利益（指数の単位）= EP_Y × PI(Y-1 年12月)
    Efy = {}
    for Y, a in ann.items():
        dec = (Y - 1) * 100 + 12
        if a['EP'] is not None and dec in PI:
            Efy[Y - 1] = a['EP'] * PI[dec]
    sig = {'CAPE': {}, 'ECY': {}, 'EY1': {}, 'RY': {}}
    for t in ks:
        Y = known_year(t) - 1                 # 使える最新の決算期
        fys = [Y - i for i in range(10) if (Y - i) in Efy and (Y - i) in cpi]
        # 連続した決算期だけ（途中の欠けがあればそこで打ち切る）
        cont = []
        for i in range(10):
            if (Y - i) in Efy and (Y - i) in cpi:
                cont.append(Y - i)
            else:
                break
        if len(cont) < 5:
            continue
        cy = t // 100 - 1                      # 価格を実質化する物価 = 前年の年平均
        if cy not in cpi:
            continue
        e_real = S.mean(Efy[f] / cpi[f] for f in cont)
        if e_real <= 0:
            continue
        cape = (PI[t] / cpi[cy]) / e_real
        sig['CAPE'][t] = cape
        sig['EY1'][t] = Efy[Y] / PI[t]
        if t in y10 and (cy - 10) in cpi:
            pi10 = (cpi[cy] / cpi[cy - 10]) ** 0.1 - 1
            sig['RY'][t] = y10[t] / 100 - pi10
            sig['ECY'][t] = 1 / cape - sig['RY'][t]
    cash, bond = {}, {}
    for k in ks:
        a = ym_add(k, -1)
        if a in cash_rate:
            cash[k] = cash_rate[a] / 1200
        if a in y10 and k in y10:
            bond[k] = par_bond_ret(y10[a] / 100, y10[k] / 100)
    return {'name': jp, 'iso2': iso2, 'mkt': dict(tr), 'usd': fc['usd'], 'cash': cash, 'bond': bond, 'sig': sig, 'PI': PI}
