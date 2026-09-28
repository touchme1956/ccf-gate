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
    D = dict(sh['D'])
    for k, v in gy['d12'].items():
        if k > max(D):
            D[k] = v
    sig = us_signals(P, E, cpi, gs10)
    sig['DY'] = {t: D[ym_add(t, -E_LAG)] / P[t] for t in P if ym_add(t, -E_LAG) in D}
    meta = {'E_ext_scale_months': len(ov), 'E_ext_months': sorted(ext_e), 'P_ext_from': min(k for k in P if k > 202309) if any(k > 202309 for k in P) else None}
    return {'mkt': mkt, 'rf': rf, 'bond': bond, 'sig': sig, 'sh': sh, 'gy': gy, 'cpi': cpi, 'gs10': gs10, 'P': P, 'E': E, 'D': D, 'meta': meta}


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
    out = {'CAPE': {}, 'ECY': {}, 'EY1': {}, 'RY': {}, 'CAPE0': {}, 'Y10': {}}
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
        if t in gs10:
            out['Y10'][t] = gs10[t] / 100
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


_FC = None


def french_countries():
    global _FC
    if _FC is not None:
        return _FC
    _FC = _french_countries()
    return _FC


def _french_countries():
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
    sig = {'CAPE': {}, 'ECY': {}, 'EY1': {}, 'RY': {}, 'Y10': {k: v / 100 for k, v in y10.items() if k in tr}}
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
    # E1 用: B/M と配当利回りを価格で毎月更新（年 Y の比率は Y 年7月から）
    for t in ks:
        Yk = known_year(t)
        a = ann.get(Yk)
        dec = (Yk - 1) * 100 + 12
        if a is None or dec not in PI:
            continue
        if a['BM'] is not None and a['BM'] > 0:
            sig.setdefault('BM', {})[t] = a['BM'] * PI[dec] / PI[t]
        if a['Yld'] is not None and a['Yld'] > 0:
            sig.setdefault('DY', {})[t] = a['Yld'] * PI[dec] / PI[t]
    return {'name': jp, 'iso2': iso2, 'mkt': dict(tr), 'usd': fc['usd'], 'cash': cash, 'bond': bond, 'sig': sig, 'PI': PI}


# ───────────────────────── 道具（統計・窓） ─────────────────────────
def qtile(v, p):
    v = sorted(v)
    return v[int(p * (len(v) - 1))]


def longest_run_to_end(ok_months):
    """条件を満たす月の集合 → 最後の月で終わる最長の連続区間（月の昇順リスト）"""
    ks = sorted(ok_months)
    if not ks:
        return []
    run = [ks[-1]]
    for k in reversed(ks[:-1]):
        if ym_add(k, 1) == run[-1]:
            run.append(k)
        else:
            break
    return sorted(run)


def tr_index(r, keys):
    """総リターンの指数（月末）。keys[0] の前月末を 1 とする"""
    idx, lv = {ym_add(keys[0], -1): 1.0}, 1.0
    for k in keys:
        lv *= 1 + r[k]
        idx[k] = lv
    return idx


def sma_state(idx, n=10):
    """月末 t の指数が n か月平均（t を含む n 個の月末）より上か → {t: True/False}"""
    ks = sorted(idx)
    out = {}
    for i in range(n - 1, len(ks)):
        w = [idx[ks[j]] for j in range(i - n + 1, i + 1)]
        out[ks[i]] = idx[ks[i]] >= sum(w) / n
    return out


def tsmom_state(s, cash, n=12):
    """月末 t に、直近 n か月（t−n+1〜t）の株の累積 > 短期金利の累積 か → {t: True/False}"""
    ks = sorted(k for k in s if k in cash)
    out = {}
    for i in range(n - 1, len(ks)):
        w = ks[i - n + 1:i + 1]
        if ym_add(w[0], n - 1) != w[-1]:
            continue
        a = b = 1.0
        for k in w:
            a *= 1 + s[k]; b *= 1 + cash[k]
        out[ks[i]] = a > b
    return out


def dd_from_high(idx):
    """月末 t の指数の、それまでの最高値からの下落率（0以下）"""
    out, hi = {}, None
    for k in sorted(idx):
        hi = idx[k] if hi is None else max(hi, idx[k])
        out[k] = idx[k] / hi - 1
    return out


def by_decade(nm, b):
    out = {}
    for d0 in range(1920, 2030, 10):
        ks = [k for k in nm if k in b and d0 * 100 <= k <= (d0 + 9) * 100 + 12]
        if len(ks) >= 24:
            out[str(d0)] = round((M.cagr([nm[k] for k in ks]) - M.cagr([b[k] for k in ks])) * 100, 2)
    return out


def dca_split(s, b, n=240, hold_end=M.HOLD_START):
    """毎月1を n か月積み立てた最終額の比（s ÷ b）を1か月刻みで。終点が保有期間に入るかで分ける"""
    ks = sorted(set(s) & set(b))
    res = []
    for i in range(0, len(ks) - n + 1):
        w = ks[i:i + n]
        if ym_add(w[0], n - 1) != w[-1]:
            continue
        ws = wb = 0.0
        for k in w:
            ws = (ws + 1) * (1 + s[k]); wb = (wb + 1) * (1 + b[k])
        res.append((w[0], w[-1], ws / wb))
    return summarize_ratios(res, hold_end)


def summarize_ratios(res, hold_end=M.HOLD_START):
    def summ(rr):
        if not rr:
            return None
        v = sorted(r for _, _, r in rr)
        return {'windows': len(v), 'win_rate': round(sum(1 for x in v if x > 1) / len(v), 3), 'median': round(v[len(v) // 2], 4),
                'p05': round(v[int(0.05 * (len(v) - 1))], 4), 'worst': [min(rr, key=lambda x: x[2])[0], round(min(r for _, _, r in rr), 4)],
                'best': [max(rr, key=lambda x: x[2])[0], round(max(r for _, _, r in rr), 4)]}
    return {'all': summ(res), 'train': summ([x for x in res if x[1] < hold_end]), 'hold': summ([x for x in res if x[1] >= hold_end])}


# ───────────────────────── P 型の道具 ─────────────────────────
def run_alloc(keys, s, alt, cash, wfun, spread=SPREAD_MARGIN, cost_unit=COST_UNIT):
    """t 月の株の割合 w = wfun(t)（t−1 月末の信号から）。w<1 の残りは alt、w>1 は借入（cash + spread）。
    費用 = |w_t − 前月の割合が値動きで変わった後の値| × cost_unit（最初の月は0）"""
    gross, net, W, TO = {}, {}, {}, {}
    wd = None
    for t in keys:
        w = wfun(t)
        rs = s[t]
        if w < 1:
            rp = w * rs + (1 - w) * alt[t]
        elif w == 1:
            rp = rs
        else:
            rp = w * rs - (w - 1) * (cash[t] + spread / 12)
        to = 0.0 if wd is None else abs(w - wd)
        gross[t] = rp
        net[t] = rp - to * cost_unit
        W[t] = w
        TO[t] = to
        wd = w * (1 + rs) / (1 + rp) if 1 + rp > 1e-9 else w
    return gross, net, W, TO


def alloc_keys(s, alt, cash, sigfun, lo, hi, need_alt=True, need_cash=False):
    ok = set()
    for t in months(lo, hi):
        if t not in s:
            continue
        if need_alt and t not in alt:
            continue
        if need_cash and t not in cash:
            continue
        if sigfun(t) is None:
            continue
        ok.add(t)
    return longest_run_to_end(ok)


def rt_forecasts(xsig, exlog, sign, min_pairs=120, horizon=12):
    """その場で分かるデータだけの回帰（拡大窓）。T 月末の予想 μ̂_T と、その時点までの平均 ȳ_T → {T: (μ̂, ȳ)}。
    組 (x_t, y_t)、y_t = t+1..t+12 の対数超過の和。T で使えるのは t ≤ T−12 の組だけ。
    sign = 理屈の係数の符号（log CAPE なら −1、ECY なら +1）。逆なら μ̂ = ȳ。μ̂ は0未満にしない"""
    ks = sorted(exlog)
    y = {}
    for i, t in enumerate(ks):
        if i + horizon < len(ks) and ym_add(t, horizon) == ks[i + horizon] and t in xsig:
            y[t] = sum(exlog[ks[i + j]] for j in range(1, horizon + 1))
    pairs = sorted(y)
    out = {}
    n = sx = sy = sxx = sxy = 0.0
    j = 0
    for T in sorted(xsig):
        while j < len(pairs) and pairs[j] <= ym_add(T, -horizon):
            t = pairs[j]
            x, yy = xsig[t], y[t]
            n += 1; sx += x; sy += yy; sxx += x * x; sxy += x * yy
            j += 1
        if n < min_pairs:
            continue
        ybar = sy / n
        vx = sxx / n - (sx / n) ** 2
        if vx <= 0:
            continue
        b = (sxy / n - (sx / n) * (sy / n)) / vx
        a = sy / n - b * sx / n
        mu = a + b * xsig[T] if b * sign > 0 else ybar
        out[T] = (max(mu, 0.0), ybar)
    return out


def rt_weight(fc, T, cap=1.5):
    if T not in fc:
        return None
    mu, ybar = fc[T]
    if ybar <= 0:
        return 0.0
    return min(cap, max(0.0, mu / ybar))


def p_rule_wfun(rule, sig, th, idxup=None, fc=None, tsm=None):
    """規則 → wfun(t)（t−1 月末の信号）。th = 閾値の辞書。idxup = 指数が10か月平均以上か、tsm = 12か月の超過が正か"""
    def g(name, t):
        return sig.get(name, {}).get(ym_add(t, -1))
    if rule == 'P1_CAPE_med_bond':
        return lambda t: None if g('CAPE', t) is None else (1.0 if g('CAPE', t) <= th['CAPE_median'] else 0.0)
    if rule == 'P2_CAPE_q75_bond' or rule == 'P3_CAPE_q75_cash':
        return lambda t: None if g('CAPE', t) is None else (0.0 if g('CAPE', t) > th['CAPE_q75'] else 1.0)
    if rule == 'P4_ECY_zero_bond':
        return lambda t: None if g('ECY', t) is None else (1.0 if g('ECY', t) > 0 else 0.0)
    if rule == 'P5_ECY_med_bond':
        return lambda t: None if g('ECY', t) is None else (1.0 if g('ECY', t) > th['ECY_median'] else 0.0)
    if rule == 'P6_ECY_q25_bond':
        return lambda t: None if g('ECY', t) is None else (0.0 if g('ECY', t) < th['ECY_q25'] else 1.0)
    if rule.startswith('P7_') or rule.startswith('P8_') or rule.startswith('P9_'):
        cap = {'P7': 1.0, 'P8': 1.5, 'P9': 2.0}[rule[:2]]
        return lambda t: None if g('ECY', t) is None else min(cap, max(0.0, g('ECY', t) / th['ECY_mean']))
    if rule == 'P10_CAPE_prop_1.5':
        return lambda t: None if g('CAPE', t) is None else min(1.5, max(0.0, th['CAPE_median'] / g('CAPE', t)))
    if rule == 'P11_FedModel_bond':
        return lambda t: None if (g('EY1', t) is None or g('Y10', t) is None) else (1.0 if g('EY1', t) > g('Y10', t) else 0.0)
    if rule in ('P12_RT_logCAPE_cash', 'P13_RT_ECY_cash'):
        return lambda t: rt_weight(fc, ym_add(t, -1))
    if rule == 'E2a_CAPEhigh_and_down':
        return lambda t: None if (g('CAPE', t) is None or idxup.get(ym_add(t, -1)) is None) else (0.0 if (g('CAPE', t) > th['CAPE_median'] and not idxup[ym_add(t, -1)]) else 1.0)
    if rule == 'E2b_ECYlow_and_down':
        return lambda t: None if (g('ECY', t) is None or idxup.get(ym_add(t, -1)) is None) else (0.0 if (g('ECY', t) < th['ECY_median'] and not idxup[ym_add(t, -1)]) else 1.0)
    if rule in ('E2c_agree_lev', 'E3b_ECY_agree_lev_cash', 'E3c_ECY_agree_lev2', 'E3d_ECY_agree_tsmom', 'E3a_CAPE_agree_lev'):
        lev = 2.0 if rule == 'E3c_ECY_agree_lev2' else 1.5
        trend = tsm if rule == 'E3d_ECY_agree_tsmom' else idxup
        use_cape = rule == 'E3a_CAPE_agree_lev'

        def f(t):
            u = trend.get(ym_add(t, -1))
            if use_cape:
                c_ = g('CAPE', t)
                if c_ is None or u is None:
                    return None
                cheap, dear = c_ <= th['CAPE_median'], c_ > th['CAPE_median']
            else:
                e = g('ECY', t)
                if e is None or u is None:
                    return None
                cheap, dear = e > th['ECY_median'], e < th['ECY_median']
            if cheap and u:
                return lev
            if dear and not u:
                return 0.0
            return 1.0
        return f
    raise KeyError(rule)


P_RULES = ['P1_CAPE_med_bond', 'P2_CAPE_q75_bond', 'P3_CAPE_q75_cash', 'P4_ECY_zero_bond', 'P5_ECY_med_bond', 'P6_ECY_q25_bond',
           'P7_ECY_prop_1.0', 'P8_ECY_prop_1.5', 'P9_ECY_prop_2.0', 'P10_CAPE_prop_1.5', 'P11_FedModel_bond',
           'P12_RT_logCAPE_cash', 'P13_RT_ECY_cash']
E2_RULES = ['E2a_CAPEhigh_and_down', 'E2b_ECYlow_and_down', 'E2c_agree_lev']
E3_RULES = ['E3a_CAPE_agree_lev', 'E3b_ECY_agree_lev_cash', 'E3c_ECY_agree_lev2', 'E3d_ECY_agree_tsmom']
CASH_ALT = {'P3_CAPE_q75_cash', 'P12_RT_logCAPE_cash', 'P13_RT_ECY_cash', 'E3b_ECY_agree_lev_cash'}
LEVER = {'P8_ECY_prop_1.5', 'P9_ECY_prop_2.0', 'P10_CAPE_prop_1.5', 'P12_RT_logCAPE_cash', 'P13_RT_ECY_cash', 'E2c_agree_lev'} | set(E3_RULES)
DESC = {
    'P1_CAPE_med_bond': 'CAPE ≤ 訓練の中央値なら株100%、超えたら10年国債',
    'P2_CAPE_q75_bond': 'CAPE > 訓練の75%点の月だけ10年国債',
    'P3_CAPE_q75_cash': 'CAPE > 訓練の75%点の月だけ短期金利',
    'P4_ECY_zero_bond': 'ECY > 0 なら株、0以下なら10年国債',
    'P5_ECY_med_bond': 'ECY > 訓練の中央値なら株、ほかは10年国債',
    'P6_ECY_q25_bond': 'ECY < 訓練の25%点の月だけ10年国債',
    'P7_ECY_prop_1.0': '株の割合 = ECY ÷ 訓練の平均（上限1）、残り10年国債',
    'P8_ECY_prop_1.5': '株の割合 = ECY ÷ 訓練の平均（上限1.5・借入 RF+1.5%）',
    'P9_ECY_prop_2.0': '株の割合 = ECY ÷ 訓練の平均（上限2・借入 RF+1.5%）',
    'P10_CAPE_prop_1.5': '株の割合 = 訓練の中央値 ÷ CAPE（上限1.5・借入）',
    'P11_FedModel_bond': 'Fed モデル: 12か月益回り > 10年金利なら株、ほかは10年国債',
    'P12_RT_logCAPE_cash': 'その場の回帰（log CAPE → 次の12か月の超過）の予想に比例（上限1.5・残り短期金利）',
    'P13_RT_ECY_cash': 'その場の回帰（ECY → 次の12か月の超過）の予想に比例（上限1.5・残り短期金利）',
    'E2a_CAPEhigh_and_down': '探索: CAPE 高い かつ 10か月線の下の月だけ10年国債',
    'E2b_ECYlow_and_down': '探索: ECY 低い かつ 10か月線の下の月だけ10年国債',
    'E2c_agree_lev': '探索: ECY 高い∧線の上→株150%／ECY 低い∧線の下→10年国債／ほか株100%',
    'E3a_CAPE_agree_lev': '探索2: CAPE 低い∧線の上→株150%／CAPE 高い∧線の下→10年国債／ほか株100%',
    'E3b_ECY_agree_lev_cash': '探索2: E2c で降りる先を短期金利にしたもの',
    'E3c_ECY_agree_lev2': '探索2: E2c で割安∧上の月を株200%にしたもの',
    'E3d_ECY_agree_tsmom': '探索2: E2c のトレンドを12か月の時系列モメンタムにしたもの',
}


def thresholds_from(sig, upto=M.TRAIN_END, lo=None):
    cv = [v for k, v in sig['CAPE'].items() if k <= upto and (lo is None or k >= lo)]
    ev = [v for k, v in sig.get('ECY', {}).items() if k <= upto and (lo is None or k >= lo)]
    th = {'n_cape': len(cv), 'n_ecy': len(ev)}
    if len(cv) >= 60:
        th.update(CAPE_median=qtile(cv, .5), CAPE_q75=qtile(cv, .75))
    if len(ev) >= 60:
        th.update(ECY_median=qtile(ev, .5), ECY_q25=qtile(ev, .25), ECY_mean=S.mean(ev))
    return th


def rule_needs(rule, th):
    if rule in ('P1_CAPE_med_bond', 'P10_CAPE_prop_1.5', 'E2a_CAPEhigh_and_down', 'E3a_CAPE_agree_lev'):
        return 'CAPE_median' in th
    if rule in ('P2_CAPE_q75_bond', 'P3_CAPE_q75_cash'):
        return 'CAPE_q75' in th
    if rule in ('P5_ECY_med_bond', 'E2b_ECYlow_and_down', 'E2c_agree_lev', 'E3b_ECY_agree_lev_cash', 'E3c_ECY_agree_lev2', 'E3d_ECY_agree_tsmom'):
        return 'ECY_median' in th
    if rule == 'P6_ECY_q25_bond':
        return 'ECY_q25' in th
    if rule[:2] in ('P7', 'P8', 'P9'):
        return 'ECY_mean' in th
    return True


def sharpe_net(nm, b, rf, a=None, z=None):
    return [M.sharpe(nm, rf, a, z), M.sharpe(b, rf, a, z)]


def eval_alloc(gm, nm, b, rf, W, TO, post_pub=None):
    e = {'full': M.excess_stats(gm, b), 'train': M.excess_stats(gm, b, z=M.TRAIN_END), 'hold': M.excess_stats(gm, b, a=M.HOLD_START),
         'recent': M.excess_stats(gm, b, a=M.RECENT_START),
         'net_full': M.excess_stats(nm, b), 'net_train': M.excess_stats(nm, b, z=M.TRAIN_END), 'cost_hold': M.excess_stats(nm, b, a=M.HOLD_START)}
    e['post_pub'] = {k: M.excess_stats(gm, b, a=a) for k, a in (post_pub or {}).items()}
    e['roll20'] = M.rolling(nm, b, 20)
    e['roll20_gross'] = M.rolling(gm, b, 20)
    e['dca20'] = dca_split(nm, b, 240)
    e['sharpe'] = {nmn: sharpe_net(nm, b, rf, a, z) for nmn, (a, z) in
                   {'full': (None, None), 'train': (None, M.TRAIN_END), 'hold': (M.HOLD_START, None), 'recent': (M.RECENT_START, None)}.items()}
    ks = sorted(W)
    e['avg_stock_weight'] = {'full': round(S.mean(W[k] for k in ks), 3), 'train': round(S.mean(W[k] for k in ks if k <= M.TRAIN_END), 3) if any(k <= M.TRAIN_END for k in ks) else None,
                             'hold': round(S.mean(W[k] for k in ks if k >= M.HOLD_START), 3) if any(k >= M.HOLD_START for k in ks) else None}
    e['turnover_per_year'] = round(S.mean(TO[k] for k in ks) * 12, 3)
    e['switches'] = sum(1 for a, c in zip(ks, ks[1:]) if abs(W[c] - W[a]) >= 0.5)
    e['maxdd'] = {'s': round(M.maxdd(nm) * 100, 1), 'b': round(M.maxdd({k: b[k] for k in nm if k in b}) * 100, 1)}
    e['by_decade_net_cagr_diff'] = by_decade(nm, b)
    e['window'] = [ks[0], ks[-1]]
    return e


# ───────────────────────── K 型（積立の工夫） ─────────────────────────
K_RULES = ['K1_BTD_h1_X10', 'K2_BTD_h1_X20', 'K3_BTD_h05_X10', 'K4_BTD_h05_X20', 'K5_DBL_SMA_2x', 'K6_DBL_SMA_all',
           'K7_VA_sell', 'K8_VA_nosell', 'K9_VSC_CAPE', 'K10_VSC_ECY', 'K11_VSW_CAPE', 'K12_VSW_ECY', 'K13_LUMP_annual', 'K14_LUMP_12m']
K_DESC = {
    'K1_BTD_h1_X10': '押し目買い: 入金は全部現金に置き、最高値から10%以上下の月に全部株へ',
    'K2_BTD_h1_X20': '押し目買い: 入金は全部現金、最高値から20%以上下の月に全部株へ',
    'K3_BTD_h05_X10': '押し目買い: 入金の半分はすぐ株・半分は現金、10%以上下で全部株へ',
    'K4_BTD_h05_X20': '押し目買い: 入金の半分はすぐ株・半分は現金、20%以上下で全部株へ',
    'K5_DBL_SMA_2x': '10か月線の上では入金の61%だけ株・39%を現金、下では最大2倍を株へ',
    'K6_DBL_SMA_all': '10か月線の上では入金の61%だけ株、下では現金を全部株へ',
    'K7_VA_sell': 'バリュー平均法（目標額に合わせて買う・売る）',
    'K8_VA_nosell': 'バリュー平均法（売らない版）',
    'K9_VSC_CAPE': 'CAPE が低いほど多く積立（0〜2倍・差は現金で調整）',
    'K10_VSC_ECY': 'ECY が高いほど多く積立（0〜2倍・差は現金で調整）',
    'K11_VSW_CAPE': 'CAPE ≤ 訓練の中央値なら積立と国債を全部株へ、ほかは積立を10年国債へ',
    'K12_VSW_ECY': 'ECY > 訓練の中央値なら積立と国債を全部株へ、ほかは積立を10年国債へ',
    'K13_LUMP_annual': '年初一括（1年分を12か月ごとにまとめて株へ）vs 毎月分割（残りは現金）',
    'K14_LUMP_12m': '一括 vs 12か月の分割（手元のまとまったお金）',
}
K_NEEDS = {'K9_VSC_CAPE': ('CAPE',), 'K10_VSC_ECY': ('ECY',), 'K11_VSW_CAPE': ('CAPE', 'bond'), 'K12_VSW_ECY': ('ECY', 'bond'),
           'K15_VSW_agree': ('ECY', 'bond'), 'K16_VSW_ECY_q25': ('ECY', 'bond')}
K_RULES2 = ['K15_VSW_agree', 'K16_VSW_ECY_q25']
K_DESC.update({'K15_VSW_agree': '探索2: ECY 低い∧10か月線の下の月だけ積立を10年国債へ、ほかは積立と国債を全部株へ',
               'K16_VSW_ECY_q25': '探索2: ECY < 訓練の25%点の月だけ積立を10年国債へ、ほかは積立と国債を全部株へ'})


def fv_equal(r, n):
    return n if abs(r) < 1e-12 else (1 + r) * ((1 + r) ** n - 1) / r


def fv_annual(r, n):
    return sum(12 * (1 + r) ** (n - 12 * k) for k in range(n // 12))


def irr(tv, n, kind):
    f = fv_equal if kind == 'monthly' else fv_annual
    lo, hi = -0.2, 0.2
    for _ in range(80):
        mid = (lo + hi) / 2
        if f(mid, n) > tv:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def k_window(rule, w, s, cash, bond, sig, up, dd, prm, tax=False):
    """1つの窓で規則と相手を回す → (最終額 規則, 最終額 相手, 入金総額)。欠けた信号があれば None"""
    c = COST_UNIT
    St = Cc = B = 0.0
    Sb = Cb = 0.0
    V = 0.0
    n = len(w)
    # 税（報告のみ・K7/K8）
    basis = basis_b = 0.0
    yr_gain = {}
    for i, t in enumerate(w):
        prev = ym_add(t, -1)
        if rule == 'K13_LUMP_annual':
            inflow = 12.0 if i % 12 == 0 else 0.0
        elif rule == 'K14_LUMP_12m':
            inflow = 12.0 if i == 0 else 0.0
        else:
            inflow = 1.0
        # ── 相手
        if rule in ('K13_LUMP_annual', 'K14_LUMP_12m'):
            Cb += inflow
            a = min(1.0, Cb)
            Cb -= a; Sb += a * (1 - c)
        else:
            Sb += inflow * (1 - c)
            basis_b += inflow
        # ── 規則
        Cc += inflow
        buy = 0.0
        if rule.startswith('K1_') or rule.startswith('K2_') or rule.startswith('K3_') or rule.startswith('K4_'):
            h, X = prm['h'], prm['X']
            buy = (1 - h) * inflow
            d = dd.get(prev)
            if d is not None and d <= -X:
                buy = Cc
        elif rule in ('K5_DBL_SMA_2x', 'K6_DBL_SMA_all'):
            h = prm['h']
            u = up.get(prev, True)   # 最初の9か月は線が無い → 『上』（ふつうの状態）として扱う（事前登録どおりの扱いを明記）
            if u:
                buy = (1 - h) * inflow
            else:
                reserve = Cc - inflow
                buy = inflow + (min(reserve, 1.0) if rule == 'K5_DBL_SMA_2x' else reserve)
        elif rule in ('K7_VA_sell', 'K8_VA_nosell'):
            V = V * (1 + prm['g']) + 1.0
            if St < V:
                buy = min((V - St) / (1 - c), Cc)
            elif St > V and rule == 'K7_VA_sell':
                x = St - V
                if tax and St > 0:
                    gain = x - basis * x / St
                    basis -= basis * x / St
                    yr_gain[t // 100] = yr_gain.get(t // 100, 0.0) + gain
                St -= x
                Cc += x * (1 - c)
        elif rule in ('K9_VSC_CAPE', 'K10_VSC_ECY'):
            if rule == 'K9_VSC_CAPE':
                v = sig['CAPE'].get(prev)
                if v is None:
                    return None
                m = min(2.0, max(0.0, prm['CAPE_median'] / v))
            else:
                v = sig['ECY'].get(prev)
                if v is None:
                    return None
                m = min(2.0, max(0.0, v / prm['ECY_mean']))
            buy = min(m * inflow, Cc)
        elif rule in ('K11_VSW_CAPE', 'K12_VSW_ECY', 'K15_VSW_agree', 'K16_VSW_ECY_q25'):
            if rule == 'K15_VSW_agree':
                v = sig['ECY'].get(prev)
                u = up.get(prev)
                if v is None or u is None:
                    return None
                cheap = not (v < prm['ECY_median'] and not u)
            elif rule == 'K16_VSW_ECY_q25':
                v = sig['ECY'].get(prev)
                if v is None:
                    return None
                cheap = not (v < prm['ECY_q25'])
            elif rule == 'K11_VSW_CAPE':
                v = sig['CAPE'].get(prev)
                if v is None:
                    return None
                cheap = v <= prm['CAPE_median']
            else:
                v = sig['ECY'].get(prev)
                if v is None:
                    return None
                cheap = v > prm['ECY_median']
            if cheap:
                Cc += B * (1 - c); B = 0.0
                buy = Cc
            else:
                B += Cc * (1 - c); Cc = 0.0
        elif rule in ('K13_LUMP_annual', 'K14_LUMP_12m'):
            buy = Cc
        elif rule == 'K0_DCA':
            buy = inflow
        buy = max(0.0, min(buy, Cc))
        Cc -= buy
        St += buy * (1 - c)
        basis += buy
        # ── 1か月の値動き
        St *= 1 + s[t]; Cc *= 1 + cash[t]; B *= 1 + (bond[t] if B else 0.0)
        Sb *= 1 + s[t]; Cb *= 1 + cash[t]
        # 年末に税を払う（報告のみ）
        if tax and (t % 100 == 12 or i == n - 1):
            g = yr_gain.pop(t // 100, 0.0)
            if g > 0:
                tx = g * 0.20315
                take = min(tx, Cc); Cc -= take; St -= tx - take
    contributed = 12.0 * (n // 12) if rule == 'K13_LUMP_annual' else (12.0 if rule == 'K14_LUMP_12m' else float(n))
    tv, tvb = St + Cc + B, Sb + Cb
    if tax:
        tv -= max(0.0, St - basis) * 0.20315
        tvb -= max(0.0, Sb - basis_b) * 0.20315
    return tv, tvb, contributed


def k_run(rule, keys, s, cash, bond, sig, up, dd, prm, n=240, tax=False, need_bond=False):
    """全部の窓（1か月刻み）→ [(起点, 終点, 比, 規則の倍率, 相手の倍率, 年率IRRの差)]"""
    out = []
    kind = 'annual' if rule == 'K13_LUMP_annual' else 'monthly'
    L = 12 if rule == 'K14_LUMP_12m' else n
    ks = sorted(keys)
    for i in range(0, len(ks) - L + 1):
        w = ks[i:i + L]
        if ym_add(w[0], L - 1) != w[-1]:
            continue
        if need_bond and any(t not in bond for t in w):
            continue
        r = k_window(rule, w, s, cash, bond, sig, up, dd, prm, tax=tax)
        if r is None:
            continue
        tv, tvb, contrib = r
        if rule == 'K14_LUMP_12m':
            d_irr = (tv / tvb) - 1  # 12か月の単純な差（年率そのもの）
        else:
            ra, rb = irr(tv, L, kind), irr(tvb, L, kind)
            d_irr = (1 + ra) ** 12 - (1 + rb) ** 12
        out.append((w[0], w[-1], tv / tvb, tv / contrib, tvb / contrib, d_irr))
    return out


def k_summary(res, hold_end=M.HOLD_START, post_start=None):
    def summ(rr):
        if not rr:
            return None
        v = sorted(x[2] for x in rr)
        irrs = sorted(x[5] for x in rr)
        return {'windows': len(v), 'win_rate': round(sum(1 for x in v if x > 1) / len(v), 3), 'median_ratio': round(v[len(v) // 2], 4),
                'worst': [min(rr, key=lambda x: x[2])[0], round(v[0], 4)], 'best': [max(rr, key=lambda x: x[2])[0], round(v[-1], 4)],
                'median_irr_diff_pct': round(irrs[len(irrs) // 2] * 100, 3), 'worst_irr_diff_pct': round(irrs[0] * 100, 3)}
    o = {'all': summ(res), 'train': summ([x for x in res if x[1] < hold_end]), 'hold': summ([x for x in res if x[1] >= hold_end])}
    if post_start:
        o['post_pub'] = summ([x for x in res if x[0] >= post_start])
    if res:
        mr = sorted(x[3] for x in res); mb = sorted(x[4] for x in res)
        o['p05_multiple'] = {'rule': round(mr[int(0.05 * (len(mr) - 1))], 3), 'bench': round(mb[int(0.05 * (len(mb) - 1))], 3)}
        o['median_multiple'] = {'rule': round(mr[len(mr) // 2], 3), 'bench': round(mb[len(mb) // 2], 3)}
    return o


def d_judge(summ, repl):
    d = {}
    tr, ho = summ.get('train'), summ.get('hold')
    d['D1_train'] = bool(tr and tr['median_ratio'] > 1 and tr['win_rate'] >= 0.8)
    d['D2_hold'] = bool(ho and ho['median_ratio'] > 1 and ho['win_rate'] >= 0.8)
    pm = summ.get('p05_multiple')
    d['D3_risk'] = bool(pm and pm['rule'] >= pm['bench'])
    if repl and repl.get('regions'):
        d['D4_repl'] = repl['positive'] / repl['regions'] >= 2 / 3
    else:
        d['D4_repl'] = None
    base = d['D1_train'] and d['D2_hold'] and d['D3_risk']
    if base and d['D4_repl'] is True:
        j = '積立で勝ち（格付け外）'
    elif base and d['D4_repl'] is None:
        j = '積立で勝ち（再現なし・格付け外）'
    else:
        j = '不合格（格付け外）'
    return j, d


# ───────────────────────── E1（割安な国を選ぶ） ─────────────────────────
def rotate(universe, signal_of, better, keys, cost_unit=COST_UNIT, frac=1 / 3):
    """universe: {国: 米ドルの月次リターン}、signal_of(国, t) → 値 or None（t 月末）、better: 'low' か 'high'。
    t 月末の信号で t+1 月を等分で持つ。戻り: gross, net, 持った国の一覧, 売買"""
    gross, net, held, TO = {}, {}, {}, {}
    wprev = None
    for t in keys:
        prev = ym_add(t, -1)
        cand = []
        for c, r in universe.items():
            if t not in r:
                continue
            v = signal_of(c, prev)
            if v is None:
                continue
            cand.append((v, c))
        if len(cand) < 6:
            continue
        cand.sort(reverse=(better == 'high'))
        k = max(1, round(len(cand) * frac))
        pick = [c for _, c in cand[:k]]
        wt = {c: 1 / k for c in pick}
        rp = sum(universe[c][t] * wt[c] for c in pick)
        if wprev is None:
            to = 0.0
        else:
            allc = set(wt) | set(wprev)
            to = 0.5 * sum(abs(wt.get(c, 0.0) - wprev.get(c, 0.0)) for c in allc)
        gross[t] = rp
        net[t] = rp - to * cost_unit
        held[t] = pick
        TO[t] = to
        # 値動き後の重み
        tot = 1 + rp
        wprev = {c: wt[c] * (1 + universe[c][t]) / tot for c in pick}
    return gross, net, held, TO


# ───────────────────────── 報告の道具 ─────────────────────────
def tax_alloc(keys, s, alt, W, rate=0.20315, c=COST_UNIT):
    """日本の課税口座の近似（報告のみ）: 1 を keys[0] に入れ、毎月初に W[t] へ売買。売った側の利益に年末課税（年内通算・繰越なし）。
    最後に全部売って課税。配当・利子は非課税の近似"""
    w0 = W[keys[0]]
    Sv, Av = w0, 1 - w0
    Sb, Ab = Sv, Av
    yr = {}
    for i, t in enumerate(keys):
        if i > 0:
            tot = Sv + Av
            x = W[t] * tot - Sv
            if x < -1e-12 and Sv > 0:
                sell = -x
                yr[t // 100] = yr.get(t // 100, 0.0) + sell - Sb * sell / Sv
                Sb -= Sb * sell / Sv; Sv -= sell
                Av += sell * (1 - c); Ab += sell * (1 - c)
            elif x > 1e-12 and Av > 0:
                sell = min(x, Av)
                yr[t // 100] = yr.get(t // 100, 0.0) + sell - Ab * sell / Av
                Ab -= Ab * sell / Av; Av -= sell
                Sv += sell * (1 - c); Sb += sell * (1 - c)
        Sv *= 1 + s[t]
        Av *= 1 + alt[t]
        if t % 100 == 12:
            g = yr.pop(t // 100, 0.0)
            if g > 0:
                tx = g * rate
                take = min(tx, Av); Av -= take; Sv -= tx - take
    g = sum(yr.values())
    tv = Sv + Av - max(0.0, g) * rate - max(0.0, (Sv - Sb) + (Av - Ab)) * rate
    bh = 1.0
    for t in keys:
        bh *= 1 + s[t]
    bh_tax = bh - max(0.0, bh - 1) * rate
    return {'after_tax_ratio': round(tv / bh_tax, 4), 'pre_tax_ratio_approx': None}


def exlog_series(s, cash):
    return {t: math.log1p(s[t]) - math.log1p(cash[t]) for t in s if t in cash}


def git_sha(path):
    try:
        return subprocess.run(['git', 'log', '-1', '--format=%h', '--', path], cwd=M.BASE, capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa
        return None


def post_pub_for(rule):
    if rule == 'E3d_ECY_agree_tsmom':
        return {'post_MOP2012': 201301}
    if rule.startswith('E2') or rule.startswith('E3'):
        return {'post_Faber2007': 200801}
    if rule == 'P11_FedModel_bond':
        return {'post_Yardeni1997': 199801}
    if rule in ('P12_RT_logCAPE_cash', 'P13_RT_ECY_cash'):
        return {'post_CampbellThompson2008': 200901}
    d = {'post_CampbellShiller1998': 199901}
    if 'ECY' in rule:
        d['post_ShillerBlackJivraj2020'] = 202101
    return d


# ───────────────────────── 本体 ─────────────────────────
def main():
    pre = json.load(open(os.path.join(M.BASE, 'out', PREREG)))
    sha = git_sha('out/' + PREREG)
    tp = pre['train_only_parameters']
    log('事前登録', PREREG, sha)
    us = us_data()
    sig, mkt, rf, bond = us['sig'], us['mkt'], us['rf'], us['bond']
    sanity = {}
    sanity['us_cagr_full'] = round(M.cagr(mkt) * 100, 2)
    sanity['us_cagr_2007'] = round(M.cagr(M.window(mkt, M.HOLD_START)) * 100, 2)
    ov = [k for k in sig['CAPE0'] if k in us['sh']['CAPE']]
    rel = [sig['CAPE0'][k] / us['sh']['CAPE'][k] - 1 for k in ov]
    sanity['cape_vs_shiller'] = {'n': len(ov), 'median_rel': round(S.median(rel), 5), 'max_abs_rel': round(max(abs(x) for x in rel), 4)}
    ov = [k for k in sig['ECY'] if k in us['sh']['ECY']]
    sanity['ecy_corr_shiller'] = round(M.corr([sig['ECY'][k] for k in ov], [us['sh']['ECY'][k] for k in ov]), 4)
    sanity['us_data_meta'] = us['meta']
    # 訓練だけの閾値（事前登録の数字と一致するか）
    th = thresholds_from(sig)
    idx = tr_index(mkt, sorted(mkt))
    up = sma_state(idx)
    dd = dd_from_high(idx)
    tsm_us = tsmom_state(mkt, rf)
    tr_up = [up[k] for k in up if k <= M.TRAIN_END]
    p_below = sum(1 for u in tr_up if not u) / len(tr_up)
    g_va = (1 + M.cagr(M.window(mkt, None, M.TRAIN_END))) ** (1 / 12) - 1
    chk = {'CAPE_median': (th['CAPE_median'], tp['CAPE_median']), 'CAPE_q75': (th['CAPE_q75'], tp['CAPE_q75']),
           'ECY_median': (th['ECY_median'], tp['ECY_median']), 'ECY_q25': (th['ECY_q25'], tp['ECY_q25']), 'ECY_mean': (th['ECY_mean'], tp['ECY_mean']),
           'SMA10_below_fraction_train': (p_below, tp['SMA10_below_fraction_train']), 'VA_g_monthly': (g_va, tp['VA_g_monthly'])}
    sanity['train_params_match_prereg'] = {k: [round(a, 6), b, abs(a - b) <= max(1e-3 * abs(b), 1e-5)] for k, (a, b) in chk.items()}
    bad = [k for k, v in sanity['train_params_match_prereg'].items() if not v[2]]
    if bad:
        raise SystemExit(f'訓練の閾値が事前登録と一致しない: {bad}')
    # 事前登録の値そのものを使う（丸めの差で規則が動かないように）
    th = {'CAPE_median': tp['CAPE_median'], 'CAPE_q75': tp['CAPE_q75'], 'ECY_median': tp['ECY_median'], 'ECY_q25': tp['ECY_q25'], 'ECY_mean': tp['ECY_mean']}
    log('訓練の閾値は事前登録と一致', th)

    # 道具の検算: w≡1 の超過は0
    ks0 = months(192607, END_M)
    g1, n1, _, _ = run_alloc(ks0, mkt, bond, rf, lambda t: 1.0)
    e1 = M.excess_stats(g1, mkt)
    sanity['w1_excess_zero'] = e1['ex_ann'] == 0 and e1['cagr_diff'] == 0
    # 後知恵の点検: P1 の w は t−1 の信号だけで決まる（t の信号を書き換えても W[t] は動かない）
    wf = p_rule_wfun('P1_CAPE_med_bond', sig, th)
    sig2 = {k: dict(v) for k, v in sig.items()}
    probe = 200001
    sig2['CAPE'][probe] = 1.0 if sig['CAPE'][probe] > th['CAPE_median'] else 999.0
    wf2 = p_rule_wfun('P1_CAPE_med_bond', sig2, th)
    sanity['no_lookahead_probe'] = {'W_t_unchanged': wf(probe) == wf2(probe), 'W_t+1_changes': wf(ym_add(probe, 1)) != wf2(ym_add(probe, 1))}

    # 回帰（P12・P13）: 1926-06 以前は Shiller の株・Goyal Rfree、以降は French
    sh, gy = us['sh'], us['gy']
    sh_tr = {}
    shk = sorted(sh['P'])
    for a, k in zip(shk, shk[1:]):
        if k in sh['D'] and k < 192607:
            sh_tr[k] = (sh['P'][k] + sh['D'][k] / 12) / sh['P'][a] - 1
    ex_us = {t: math.log1p(v) - math.log1p(gy['Rfree'][t]) for t, v in sh_tr.items() if t in gy['Rfree']}
    ex_us.update(exlog_series(mkt, rf))
    fc12 = rt_forecasts({t: math.log(v) for t, v in sig['CAPE'].items()}, ex_us, sign=-1)
    fc13 = rt_forecasts(sig['ECY'], ex_us, sign=+1)
    FC = {'P12_RT_logCAPE_cash': fc12, 'P13_RT_ECY_cash': fc13}

    # 国のデータ
    cpi_all = wb_cpi()
    C = {}
    for f in COUNTRIES:
        cd = country_data(f, cpi_all)
        cd['th'] = thresholds_from(cd['sig'])
        ksc = sorted(cd['mkt'])
        cd['idx'] = tr_index(cd['mkt'], ksc)
        cd['up'] = sma_state(cd['idx'])
        cd['dd'] = dd_from_high(cd['idx'])
        cd['tsm'] = tsmom_state(cd['mkt'], cd['cash'])
        exc = exlog_series(cd['mkt'], cd['cash'])
        cd['fc'] = {'P12_RT_logCAPE_cash': rt_forecasts({t: math.log(v) for t, v in cd['sig']['CAPE'].items()}, exc, sign=-1),
                    'P13_RT_ECY_cash': rt_forecasts(cd['sig']['ECY'], exc, sign=+1)}
        C[f] = cd
    log('国のデータ', len(C), 'か国')

    tested = []

    # ── P 族と E2 族（米国＋18か国の再現）
    def p_eval(rule, fam):
        wf = p_rule_wfun(rule, sig, th, idxup=up, fc=FC.get(rule), tsm=tsm_us)
        alt = rf if rule in CASH_ALT else bond
        keys = alloc_keys(mkt, alt, rf, wf, 192607, END_M, need_alt=True, need_cash=rule in LEVER)
        gm, nm, W, TO = run_alloc(keys, mkt, alt, rf, wf)
        e = eval_alloc(gm, nm, mkt, rf, W, TO, post_pub_for(rule))
        # 米国外の再現
        det, pos, reg = {}, 0, 0
        for f, cd in C.items():
            if not rule_needs(rule, cd['th']):
                det[cd['name']] = 'N/A（訓練期間の信号が60か月未満）'
                continue
            wfc = p_rule_wfun(rule, cd['sig'], cd['th'], idxup=cd['up'], fc=cd['fc'].get(rule), tsm=cd['tsm'])
            altc = cd['cash'] if rule in CASH_ALT else cd['bond']
            kc = alloc_keys(cd['mkt'], altc, cd['cash'], wfc, 197501, 202512, need_alt=True, need_cash=rule in LEVER)
            if len(kc) < 120:
                det[cd['name']] = f'N/A（評価できる期間が {len(kc)} か月）'
                continue
            gc, nc, Wc, _ = run_alloc(kc, cd['mkt'], altc, cd['cash'], wfc)
            xs = M.excess_stats(nc, cd['mkt'])
            xh = M.excess_stats(nc, cd['mkt'], a=M.HOLD_START)
            reg += 1
            ok = xs['ex_ann'] > 0 and xs['cagr_diff'] > 0
            pos += ok
            det[cd['name']] = {'window': [kc[0], kc[-1]], 'net_ex_ann': xs['ex_ann'], 'net_cagr_diff': xs['cagr_diff'], 't': xs['t'],
                               'hold_net_ex_ann': xh['ex_ann'] if xh else None, 'hold_net_cagr_diff': xh['cagr_diff'] if xh else None,
                               'avg_w': round(S.mean(Wc.values()), 3), 'positive': ok}
        e['repl'] = {'regions': reg, 'positive': pos, 'detail': det}
        # 報告: Shiller 時代（1881〜1926・独立ではない）
        e['shiller_era'] = None
        if not rule.startswith('E2') or True:
            shb = {k: sh['BOND'][ym_add(k, -1)] - 1 for k in sh_tr if ym_add(k, -1) in sh['BOND']}
            shc = {k: gy['Rfree'][k] for k in sh_tr if k in gy['Rfree']}
            idx_sh = tr_index(sh_tr, sorted(sh_tr))
            wfs = p_rule_wfun(rule, sig, th, idxup=sma_state(idx_sh), fc=FC.get(rule), tsm=tsmom_state(sh_tr, shc))
            alt_s = shc if rule in CASH_ALT else shb
            ksh = [k for k in alloc_keys(sh_tr, alt_s, shc, wfs, 187102, 192606, need_alt=True, need_cash=rule in LEVER)]
            if len(ksh) >= 120:
                gs_, ns_, Ws_, _ = run_alloc(ksh, sh_tr, alt_s, shc, wfs)
                e['shiller_era'] = {'net': M.excess_stats(ns_, sh_tr), 'avg_w': round(S.mean(Ws_.values()), 3)}
        # 報告: 借入 RF+0.5%
        if rule in LEVER:
            gf, nf, _, _ = run_alloc(keys, mkt, alt, rf, wf, spread=0.005)
            e['report_spread_0.5'] = {'cost_hold': M.excess_stats(nf, mkt, a=M.HOLD_START), 'sharpe_hold': sharpe_net(nf, mkt, rf, M.HOLD_START, None)}
        # 報告: 課税口座（切替の型だけ・保有期間に一括1）
        if max(W.values()) <= 1:
            hk = [k for k in keys if k >= M.HOLD_START]
            e['report_tax_hold'] = tax_alloc(hk, mkt, alt, W)
        return {'name': rule, 'family': fam, 'description': DESC[rule], 'graded': True, **e}

    P = [p_eval(r, 'P（主）') for r in P_RULES]
    E2 = [p_eval(r, 'E2（探索）') for r in E2_RULES]
    E3 = [p_eval(r, 'E3（探索2・第1族の結果を見た後に登録）') for r in E3_RULES]
    for fam in (P, E2, E3):
        hp = M.holm({x['name']: x['hold']['p'] for x in fam})
        for x in fam:
            x['holm_p'] = hp.get(x['name'])
            sp = {'train': tuple(x['sharpe']['train']), 'hold': tuple(x['sharpe']['hold'])}
            gr, cr = M.grade(x['full'], x['train'], x['hold'], x['roll20'], cost_hold=x['cost_hold'], repl=x['repl'],
                             family_holm_p=x['holm_p'], sharpe_pair=sp, leveraged_or_timing=True)
            x['grade'], x['criteria'] = gr, cr
            log(f"{x['name']:24s} {gr} 訓練 {x['train']['ex_ann']:+.2f}(t{x['train']['t']}) 保有 {x['hold']['ex_ann']:+.2f}(t{x['hold']['t']}) "
                f"幾何差 {x['hold']['cagr_diff']:+.2f} 費用後 {x['cost_hold']['cagr_diff']:+.2f} 20年勝率 {x['roll20']['win_rate'] if x['roll20'] else None} "
                f"再現 {x['repl']['positive']}/{x['repl']['regions']} シャープ保有 {x['sharpe']['hold']} 株平均 {x['avg_stock_weight']}")
    tested += P + E2 + E3

    # ── 事後の点検（第1・2族の結果を見た後・格付けしない）: 一致の型の頑健さ（米国）
    def agree_w(thr, trend, lev, lag=1):
        def f(t):
            k = ym_add(t, -lag)
            e, u = sig['ECY'].get(k), trend.get(k)
            if e is None or u is None:
                return None
            if e > thr and u:
                return lev
            if e < thr and not u:
                return 0.0
            return 1.0
        return f
    ecy_tr = [v for k, v in sig['ECY'].items() if k <= M.TRAIN_END]
    up8, up12 = sma_state(idx, 8), sma_state(idx, 12)
    grid = {}
    for lev in (1.5, 2.0):
        vs = {'基準': (th['ECY_median'], up, 1, COST_UNIT, SPREAD_MARGIN, bond),
              '信号をさらに1か月遅らせる': (th['ECY_median'], up, 2, COST_UNIT, SPREAD_MARGIN, bond),
              '8か月線': (th['ECY_median'], up8, 1, COST_UNIT, SPREAD_MARGIN, bond),
              '12か月線': (th['ECY_median'], up12, 1, COST_UNIT, SPREAD_MARGIN, bond),
              'ECY の線を訓練の40%点': (qtile(ecy_tr, .40), up, 1, COST_UNIT, SPREAD_MARGIN, bond),
              'ECY の線を訓練の60%点': (qtile(ecy_tr, .60), up, 1, COST_UNIT, SPREAD_MARGIN, bond),
              '借入 RF+3%': (th['ECY_median'], up, 1, COST_UNIT, 0.03, bond),
              '売買費用 0.30%': (th['ECY_median'], up, 1, 0.003, SPREAD_MARGIN, bond),
              '降りる先を短期金利': (th['ECY_median'], up, 1, COST_UNIT, SPREAD_MARGIN, rf)}
        for vn, (thr, trend, lag, cu, sp, alt) in vs.items():
            wf = agree_w(thr, trend, lev, lag)
            keys = alloc_keys(mkt, alt, rf, wf, 192607, END_M, need_alt=True, need_cash=True)
            gm, nm, W, TO = run_alloc(keys, mkt, alt, rf, wf, spread=sp, cost_unit=cu)
            h = M.excess_stats(nm, mkt, a=M.HOLD_START)
            h10 = M.excess_stats(nm, mkt, a=201001)
            f_ = M.excess_stats(nm, mkt)
            tr_ = M.excess_stats(nm, mkt, z=M.TRAIN_END)
            grid[f'倍率{lev}・{vn}'] = {'train_net': [tr_['ex_ann'], tr_['t']], 'hold_net': [h['ex_ann'], h['t'], h['cagr_diff']],
                                      'from_2010_net': [h10['ex_ann'], h10['t'], h10['cagr_diff']], 'full_net_t': f_['t'],
                                      'sharpe_hold': sharpe_net(nm, mkt, rf, M.HOLD_START, None),
                                      'maxdd_hold': [round(M.maxdd(M.window(nm, M.HOLD_START)) * 100, 1), round(M.maxdd(M.window(mkt, M.HOLD_START)) * 100, 1)]}
            log(f"事後の点検 倍率{lev} {vn:22s} 訓練 {tr_['ex_ann']:+.2f}(t{tr_['t']}) 保有 {h['ex_ann']:+.2f}(t{h['t']}) 幾何 {h['cagr_diff']:+.2f} "
                f"2010〜 {h10['cagr_diff']:+.2f} 全期間t {f_['t']}")
    posthoc = {'agree_robustness_grid_US': grid,
               'note': '事後（第1・2族の結果を見た後）の点検。格付けしない。どれか一つが良くても採用の根拠にしない（選び直しになる）。全部の向きがそろうかだけを見る'}

    # ── E1（割安な国を選ぶ）
    jd = M.jkp_mkt('developed', 'vw')
    bench_w = {t: jd[t] + rf[t] for t in jd if t in rf}
    uni = {f: C[f]['usd'] for f in C}
    uni['US'] = mkt
    sigs = {f: C[f]['sig'] for f in C}
    sigs['US'] = {'CAPE': sig['CAPE'], 'DY': sig['DY']}
    # 相対 CAPE（それまでの中央値・最低60か月）
    import bisect
    relc = {}
    for c, sg in sigs.items():
        arr, out = [], {}
        for t in sorted(sg['CAPE']):
            bisect.insort(arr, sg['CAPE'][t])
            if len(arr) >= 60:
                n = len(arr)
                med = arr[n // 2] if n % 2 else (arr[n // 2 - 1] + arr[n // 2]) / 2
                out[t] = sg['CAPE'][t] / med
        relc[c] = out

    def sig_get(name):
        def f(c, t):
            if name == 'CAPE_rel':
                return relc[c].get(t)
            if name == 'BM' and c == 'US':
                return None
            return sigs[c].get(name, {}).get(t)
        return f

    def combo(c, t):
        rs = []
        for name, better in (('CAPE', 'low'), ('BM', 'high'), ('DY', 'high')):
            fget = sig_get(name)
            vals = [(fget(cc, t), cc) for cc in uni if fget(cc, t) is not None]
            me = fget(c, t)
            if me is None or len(vals) < 6:
                continue
            v = sorted(x for x, _ in vals)
            r = sum(1 for x in v if x < me) / (len(v) - 1)   # 0=最小
            rs.append(r if better == 'low' else 1 - r)
        return S.mean(rs) if rs else None

    # 勢い（12-1）: 月末 T の値 = T−11〜T−1 月の米ドル建て累積リターン
    mom = {}
    for c, r in uni.items():
        out = {}
        for T in r:
            ks_ = [ym_add(T, -j) for j in range(1, 12)]
            if all(k in r for k in ks_):
                v = 1.0
                for k in ks_:
                    v *= 1 + r[k]
                out[T] = v - 1
        mom[c] = out

    def sig_any(name):
        if name == 'MOM':
            return lambda c, t: mom[c].get(t)
        return sig_get(name)

    def combo_of(parts, require_all):
        def f(c, t):
            rs = []
            for name, better in parts:
                fget = sig_any(name)
                me = fget(c, t)
                if me is None:
                    if require_all:
                        return None
                    continue
                vals = [fget(cc, t) for cc in uni]
                v = sorted(x for x in vals if x is not None)
                if len(v) < 6:
                    if require_all:
                        return None
                    continue
                r = sum(1 for x in v if x < me) / (len(v) - 1)
                rs.append(r if better == 'low' else 1 - r)
            return S.mean(rs) if rs else None
        return f

    kE = [t for t in months(198601, 202512) if t in bench_w]
    ew_all = {}
    for t in kE:
        v = [uni[c][t] for c in uni if t in uni[c]]
        if len(v) >= 10:
            ew_all[t] = S.mean(v)

    # ★相手の訂正（事前登録の誤り）: JKP の 'developed' は『米国を除く先進国』だった
    #   （検算: 2007〜2025 の年率 5.13% ≒ French Developed_ex_US 5.27%、JKP usa 10.34%）。
    #   米国を含む19か国の型の公式の相手は、全体の事前登録の『同じ地域の時価加重の市場』に従い
    #   French Developed（米国を含む先進国・1990-07〜）に替える（米国が強かった期間なので厳しい側への訂正）。
    #   米国を除く18か国の型（E1c・E4b）は JKP developed（＝米国を除く）がそのまま正しい相手。
    dev_incl = {}
    for tt, v in M.french_tables('Developed_3_Factors').items():
        if v['freq'] == 'monthly':
            i, irf = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
            dev_incl = {k: (row[i] + row[irf]) / 100 for k, row in v['data'].items() if row[i] is not None and row[irf] is not None}
            break
    sanity['jkp_developed_is_ex_us'] = {'jkp_developed_cagr_2007_2025': round(M.cagr(M.window(bench_w, 200701, 202512)) * 100, 2),
                                        'french_developed_incl_us_cagr_2007_2025': round(M.cagr(M.window(dev_incl, 200701, 202512)) * 100, 2),
                                        'us_cagr_2007_2025': round(M.cagr(M.window(mkt, 200701, 202512)) * 100, 2)}

    def rot_stats(gm, nm, nm3, b):
        return {'full': M.excess_stats(gm, b), 'train': M.excess_stats(gm, b, z=M.TRAIN_END), 'hold': M.excess_stats(gm, b, a=M.HOLD_START),
                'recent': M.excess_stats(gm, b, a=M.RECENT_START), 'cost_hold': M.excess_stats(nm, b, a=M.HOLD_START),
                'cost_hold_0.30': M.excess_stats(nm3, b, a=M.HOLD_START),
                'post_pub': {'post_Faber2012': M.excess_stats(gm, b, a=201301), 'post_AMP2013': M.excess_stats(gm, b, a=201401)},
                'roll20': M.rolling(nm, b, 20), 'dca20': dca_split(nm, b, 240),
                'sharpe': {'train': sharpe_net(nm, b, rf, None, M.TRAIN_END), 'hold': sharpe_net(nm, b, rf, M.HOLD_START, None)},
                'by_decade_net_cagr_diff': by_decade(nm, b),
                'maxdd': {'s': round(M.maxdd(nm) * 100, 1), 'b': round(M.maxdd({k: b[k] for k in nm if k in b}) * 100, 1)}}

    def rot_family(specs, famname):
        out = []
        for name, fget, better, desc in specs:
            gm, nm, held, TO = rotate(uni, fget, better, kE)
            _, nm3, _, _ = rotate(uni, fget, better, kE, cost_unit=0.003)
            incl_us = any('US' in held[t] for t in held) or name in ('E1a_CAPE_abs', 'E1b_CAPE_rel', 'E1d_DY', 'E1e_combo', 'E4a_CAPE_MOM')
            if incl_us:
                e = rot_stats(gm, nm, nm3, dev_incl)
                e['benchmark'] = 'French Developed（米国を含む先進国・時価加重・1990-07〜）＝訂正後の公式の相手'
                e['vs_prereg_benchmark_jkp_developed_exUS'] = rot_stats(gm, nm, nm3, bench_w)
            else:
                e = rot_stats(gm, nm, nm3, bench_w)
                e['benchmark'] = 'JKP developed vw（＝米国を除く先進国・時価加重）＋French RF'
                e['vs_french_developed_incl_us'] = {'full': M.excess_stats(gm, dev_incl), 'hold': M.excess_stats(gm, dev_incl, a=M.HOLD_START)}
            e.update({'vs_equal_weight_19': {'full': M.excess_stats(gm, ew_all), 'hold': M.excess_stats(gm, ew_all, a=M.HOLD_START)},
                      'vs_us_market': {'full': M.excess_stats(gm, mkt), 'hold': M.excess_stats(gm, mkt, a=M.HOLD_START)},
                      'turnover_per_year': round(S.mean(TO.values()) * 12, 3), 'window': [min(gm), max(gm)],
                      'us_held_share': round(sum(1 for t in held if 'US' in held[t]) / len(held), 3),
                      'held_last': [C[c]['name'] if c in C else '米国' for c in held[max(held)]]})
            cnt = {}
            for t in held:
                for c in held[t]:
                    cnt[c] = cnt.get(c, 0) + 1
            e['held_share_by_country'] = {C[c]['name'] if c in C else '米国': round(v / len(held), 3) for c, v in sorted(cnt.items(), key=lambda x: -x[1])}
            out.append({'name': name, 'family': famname, 'description': desc, 'graded': True, 'repl': None, **e})
        hp = M.holm({x['name']: x['hold']['p'] for x in out})
        for x in out:
            x['holm_p'] = hp.get(x['name'])
            gr, cr = M.grade(x['full'], x['train'], x['hold'], x['roll20'], cost_hold=x['cost_hold'], repl=None, family_holm_p=x['holm_p'], leveraged_or_timing=False)
            x['grade'], x['criteria'] = gr, cr
            if 'vs_prereg_benchmark_jkp_developed_exUS' in x:
                v = x['vs_prereg_benchmark_jkp_developed_exUS']
                g2, c2 = M.grade(v['full'], v['train'], v['hold'], v['roll20'], cost_hold=v['cost_hold'], repl=None, family_holm_p=None, leveraged_or_timing=False)
                v['grade_if_prereg_benchmark'] = g2
            log(f"{x['name']:16s} {gr} 訓練 {x['train']['ex_ann']:+.2f}(t{x['train']['t']}) 保有 {x['hold']['ex_ann']:+.2f}(t{x['hold']['t']}) "
                f"幾何差 {x['hold']['cagr_diff']:+.2f} 費用後 {x['cost_hold']['cagr_diff']:+.2f} 全期間 t{x['full']['t']} 20年勝率 {x['roll20']['win_rate'] if x['roll20'] else None} "
                f"米国を持った割合 {x['us_held_share']} 相手 {x['benchmark'][:22]}")
        return out

    e1_specs = [('E1a_CAPE_abs', sig_get('CAPE'), 'low', '国の CAPE の低い1/3（19か国・等分・米ドル）'),
                ('E1b_CAPE_rel', sig_get('CAPE_rel'), 'low', '国の CAPE ÷ その国のそれまでの中央値 の低い1/3'),
                ('E1c_BM', sig_get('BM'), 'high', '国の B/M の高い1/3（米国を除く18か国）'),
                ('E1d_DY', sig_get('DY'), 'high', '国の配当利回りの高い1/3'),
                ('E1e_combo', combo, 'low', 'CAPE・B/M・配当利回りの順位の平均が良い1/3')]
    E1 = rot_family(e1_specs, 'E1（探索・国の選択）')
    e4_specs = [('E4a_CAPE_MOM', combo_of([('CAPE', 'low'), ('MOM', 'high')], True), 'low', '探索2: 国の CAPE の順位と勢い（12-1）の順位の平均が良い1/3（19か国）'),
                ('E4b_BM_MOM', combo_of([('BM', 'high'), ('MOM', 'high')], True), 'low', '探索2: 国の B/M の順位と勢いの順位の平均が良い1/3（米国を除く18か国）')]
    E4 = rot_family(e4_specs, 'E4（探索2・国の割安×勢い・第1族の結果を見た後に登録）')
    tested += E1 + E4

    # ── K 族（積立の工夫）
    K = []
    keys_us = months(192607, END_M)
    prm_us = {'CAPE_median': th['CAPE_median'], 'ECY_mean': th['ECY_mean'], 'ECY_median': th['ECY_median'], 'ECY_q25': th['ECY_q25'], 'g': tp['VA_g_monthly']}
    kparam = {'K1_BTD_h1_X10': {'h': 1.0, 'X': 0.10}, 'K2_BTD_h1_X20': {'h': 1.0, 'X': 0.20}, 'K3_BTD_h05_X10': {'h': 0.5, 'X': 0.10},
              'K4_BTD_h05_X20': {'h': 0.5, 'X': 0.20}, 'K5_DBL_SMA_2x': {'h': tp['DBL_h']}, 'K6_DBL_SMA_all': {'h': tp['DBL_h']}}
    # 検算: 規則 = 単純積立 → 比 1
    chk = k_run('K0_DCA', keys_us[:300], mkt, rf, bond, sig, up, dd, {})
    sanity['k0_ratio_is_one'] = all(abs(x[2] - 1) < 1e-12 for x in chk)
    post = {'K7_VA_sell': 199201, 'K8_VA_nosell': 199201, 'K13_LUMP_annual': 201301, 'K14_LUMP_12m': 201301}
    for rule in K_RULES + K_RULES2:
        prm = dict(prm_us, **kparam.get(rule, {}))
        need_bond = 'bond' in K_NEEDS.get(rule, ())
        res = k_run(rule, keys_us, mkt, rf, bond, sig, up, dd, prm, need_bond=need_bond)
        sm = k_summary(res, post_start=post.get(rule))
        # 10年窓（起点 2007-01 以降だけ・報告）
        r10 = [x for x in k_run(rule, [k for k in keys_us if k >= M.HOLD_START], mkt, rf, bond, sig, up, dd, prm, n=120, need_bond=need_bond)] if rule != 'K14_LUMP_12m' else []
        sm['hold_only_10y_windows'] = k_summary(r10)['all'] if r10 else None
        if rule in ('K7_VA_sell', 'K8_VA_nosell'):
            rt = k_run(rule, keys_us, mkt, rf, bond, sig, up, dd, prm, tax=True)
            sm['taxable_account'] = k_summary(rt)
        # 米国外の再現
        det, pos, reg = {}, 0, 0
        for f, cd in C.items():
            kc = longest_run_to_end([k for k in cd['mkt'] if k in cd['cash']])
            need = K_NEEDS.get(rule, ())
            cth = cd['th']
            prm_c = {}
            if rule in ('K9_VSC_CAPE', 'K11_VSW_CAPE'):
                if 'CAPE_median' not in cth:
                    det[cd['name']] = 'N/A（訓練の CAPE が60か月未満）'; continue
                prm_c['CAPE_median'] = cth['CAPE_median']
            if rule == 'K10_VSC_ECY':
                if 'ECY_mean' not in cth:
                    det[cd['name']] = 'N/A（訓練の ECY が60か月未満）'; continue
                prm_c['ECY_mean'] = cth['ECY_mean']
            if rule in ('K12_VSW_ECY', 'K15_VSW_agree'):
                if 'ECY_median' not in cth:
                    det[cd['name']] = 'N/A（訓練の ECY が60か月未満）'; continue
                prm_c['ECY_median'] = cth['ECY_median']
            if rule == 'K16_VSW_ECY_q25':
                if 'ECY_q25' not in cth:
                    det[cd['name']] = 'N/A（訓練の ECY が60か月未満）'; continue
                prm_c['ECY_q25'] = cth['ECY_q25']
            if rule in ('K5_DBL_SMA_2x', 'K6_DBL_SMA_all'):
                tu = [cd['up'][k] for k in cd['up'] if k <= M.TRAIN_END and k in kc]
                pc = sum(1 for u in tu if not u) / len(tu)
                prm_c['h'] = pc / (1 - pc)
            elif rule in kparam:
                prm_c.update(kparam[rule])
            if rule in ('K7_VA_sell', 'K8_VA_nosell'):
                trk = [k for k in kc if k <= M.TRAIN_END]
                prm_c['g'] = (1 + M.cagr({k: cd['mkt'][k] for k in trk})) ** (1 / 12) - 1
            res_c = k_run(rule, kc, cd['mkt'], cd['cash'], cd['bond'], cd['sig'], cd['up'], cd['dd'], prm_c, need_bond='bond' in need)
            if len(res_c) < 24:
                det[cd['name']] = f'N/A（窓が {len(res_c)} 個）'; continue
            smc = k_summary(res_c)['all']
            reg += 1
            ok = smc['median_ratio'] > 1
            pos += ok
            det[cd['name']] = {'windows': smc['windows'], 'median_ratio': smc['median_ratio'], 'win_rate': smc['win_rate'],
                               'median_irr_diff_pct': smc['median_irr_diff_pct'], 'positive': ok,
                               'params': {k: round(v, 5) for k, v in prm_c.items()}}
        repl = {'regions': reg, 'positive': pos, 'detail': det}
        j, dcrit = d_judge(sm, repl)
        K.append({'name': rule, 'family': 'K（積立の工夫・格付け外）' if rule in K_RULES else 'K2（積立の工夫・探索2・格付け外）', 'description': K_DESC[rule], 'graded': False, 'grade': j,
                  'D_criteria': dcrit, 'summary': sm, 'repl': repl, 'params': prm if rule not in ('K13_LUMP_annual', 'K14_LUMP_12m') else {}})
        a, t_, h_ = sm['all'], sm['train'], sm['hold']
        log(f"{rule:18s} {j} 訓練の窓 中央 {t_['median_ratio'] if t_ else None} 勝率 {t_['win_rate'] if t_ else None} ／ 保有の窓 中央 {h_['median_ratio'] if h_ else None} "
            f"勝率 {h_['win_rate'] if h_ else None} ／ IRR差 中央 {a['median_irr_diff_pct']}% ／ 5%点 {sm['p05_multiple']} ／ 再現 {pos}/{reg}")
    tested += K

    n_tested = len(tested)
    out = {'angle': 'valdca', 'prereg': PREREG, 'prereg_commit': sha,
           'prereg_parts': {PREREG: sha, 'mw_valdca_prereg2.json': git_sha('out/mw_valdca_prereg2.json')}, 'sanity': sanity,
           'train_only_parameters_used': dict(th, DBL_h=tp['DBL_h'], VA_g_monthly=tp['VA_g_monthly']),
           'posthoc': posthoc,
           'n_tested': n_tested, 'grades': {x['name']: x['grade'] for x in tested},
           'tested': tested, 'log': LOG}
    p = M.save(OUT, out)
    log('書いた', p, 'n_tested', n_tested)


if __name__ == '__main__':
    main()
