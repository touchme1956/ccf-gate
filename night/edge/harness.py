#!/usr/bin/env python3
"""night/edge/harness.py — 「市場に勝てる規則」を探す研究（2026-09-28 ユーザー「市場に勝てる歴史検証が出るまで…探し続けて」）の共有部品

★事前登録 out/edge_prereg.json の決まりを**コードで守る**ための部品。読むだけ・門の採点に不使用。

  ■ 覗き見の防止（いちばん大事）
    環境変数 EDGE_PHASE が 'select'（既定）のあいだ、すべての読み込み関数は **SEL_END（2000-12）までのデータしか返さない**。
    規則の候補を振って一つ選ぶ作業（選定）はこの状態でしか行わない。'holdout' にして全期間を読むのは、
    選んだ規則を凍結（out/edge/spec_*.json をコミット）した後の night/edge/evaluate.py だけ。
    ⚠ ここを通さずに生データを読むと、この研究の結論はすべて無効になる。

  ■ 読み込み（すべて月次は {YYYYMM: 小数}、日次は {YYYYMMDD: 小数}）
    us_market() / us_market_daily()   Ken French 米国市場（Mkt-RF＋RF）・RF（1926-07〜）
    french(name)                      French の任意の CSV zip → {見出し: {列: {日付: 値(%のまま)}}}
    french_countries(ccy)             21か国の Value-Weight {Dollar|Local} Returns（1975〜）
    french_region(region, daily)      Developed/Japan/Europe/Asia_Pacific_ex_Japan/North_America/Emerging の3因子（Mkt-RF＋RF・米ドル）
    jkp(region, key, kind, w)         JKP（jkpfactors.com）の因子 or 三分位ポートフォリオ
    shiller()                         Shiller ie_data.xls（1871〜・月次の行）
    fred(sid)                         FRED
    yahoo(sym)                        Yahoo の月次 adjclose（配当込み）
  ■ 計算
    stats(ret, bench, rf, a, b)       年率・超過・t・ぶれ・最大下落・転がる10年の勝率
    lev_daily(r, rf, L, ...)          毎日リセットの L 倍（借入 rf＋spread・経費）→ 日次
    to_monthly(daily)                 日次 → 月次の複利
キャッシュは out/_edge_cache/（repo に入れない）
"""
import csv, io, json, math, os, statistics as S, sys, time, urllib.request, zipfile, datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(BASE, 'out', '_edge_cache')
PHASE = os.environ.get('EDGE_PHASE', 'select')
SEL_END = int(os.environ.get('EDGE_SEL_END', '200012'))   # 選定に使ってよい最後の月（EDGE_SEL_END は night/edge/prefix_check.py の先読み検査だけが前へずらす）
HOLD_START = 200101         # 検定（ホールドアウト）の最初の月
FR = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{}_CSV.zip'
UA = {'User-Agent': 'Mozilla/5.0 (ccf-gate research)'}


# ───────────────────────── 覗き見の防止 ─────────────────────────
def guard(series):
    """選定の段では SEL_END より後を捨てる。キーは YYYYMMDD（日次）/ YYYYMM（月次）/ YYYY（年次）
    ⚠ 年次の表（French の Annual）は4桁の年なので、そのまま SEL_END と比べると 2005 ≤ 200012 で素通りする——年は12月として比べる"""
    if PHASE != 'select' or not series:
        return series
    out = {}
    for k, v in series.items():
        m = k // 100 if k > 999999 else (k if k > 9999 else k * 100 + 12)
        if m <= SEL_END:
            out[k] = v
    return out


def guard_nested(d):
    return {k: (guard(v) if isinstance(v, dict) and v and isinstance(next(iter(v)), int) else
                guard_nested(v) if isinstance(v, dict) else v) for k, v in d.items()}


# ───────────────────────── 取得とキャッシュ ─────────────────────────
def _get(url, tries=4, timeout=180):
    hd = {'User-Agent': 'curl/8.5.0'} if 'stlouisfed.org' in url else UA
    for a in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=hd), timeout=timeout).read()
        except Exception:
            if a == tries - 1:
                raise
            time.sleep(4 * (a + 1))


def cached(name, url, days=30):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name.replace('/', '_'))
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < days * 86400 and os.path.getsize(p) > 100:
        return open(p, 'rb').read()
    b = _get(url)
    open(p + '.part', 'wb').write(b)
    os.replace(p + '.part', p)
    return b


# ───────────────────────── Ken French ─────────────────────────
def _french_raw(name):
    z = zipfile.ZipFile(io.BytesIO(cached(f'fr_{name}.zip', FR.format(name))))
    return z.read(z.namelist()[0]).decode('latin-1').split('\n')


def french(name):
    """French の CSV を見出しごとに読む → {見出し: {列: {日付(int): 値(%)}}}。-99.99/-999 は欠測。**guard 済み**
    見出しの無い最初の表は '' という見出しで入る"""
    L = _french_raw(name)
    out, title, hdr = {}, '', None
    for l in L:
        p = [x.strip() for x in l.split(',')]
        if p and p[0].isdigit() and hdr:
            for h, v in zip(hdr[1:], p[1:]):
                try:
                    f = float(v)
                except ValueError:
                    continue
                if f > -99:
                    out.setdefault(title, {}).setdefault(h, {})[int(p[0])] = f
            continue
        if len(p) > 1 and p[0] == '' and any(p[1:]):          # 列名の行（先頭が空）
            hdr = p
            continue
        s = l.strip()
        if s and not s[0].isdigit():
            title, hdr = s, None
    return {t: {c: guard(v) for c, v in cols.items()} for t, cols in out.items()}


def us_market():
    """(mkt, rf)：米国市場の月次トータルリターンと短期金利（小数）。1926-07〜"""
    d = french('F-F_Research_Data_Factors')
    t = next(iter(d))                 # 最初の表＝月次
    mk, rf = d[t]['Mkt-RF'], d[t]['RF']
    return {m: (mk[m] + rf[m]) / 100 for m in mk if m in rf and m > 9999}, {m: rf[m] / 100 for m in rf if m > 9999}


def us_market_daily():
    d = french('F-F_Research_Data_Factors_daily')
    t = next(iter(d))
    mk, rf = d[t]['Mkt-RF'], d[t]['RF']
    return {k: (mk[k] + rf[k]) / 100 for k in mk if k in rf}, {k: rf[k] / 100 for k in rf}


def french_countries(ccy='Dollar'):
    """{国: {YYYYMM: 小数}}（Value-Weight・All 4 Data Items Not Reqd の Mkt 列）。1975〜。guard 済み"""
    z = zipfile.ZipFile(io.BytesIO(cached('fr_F-F_International_Countries.zip',
                                          'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_International_Countries.zip')))
    out = {}
    for fn in z.namelist():
        if not fn.lower().endswith('.dat'):
            continue
        L = z.read(fn).decode('latin-1').split('\n')
        head = f'Value-Weight {ccy}'
        try:
            i = next(k for k, l in enumerate(L) if head in l and 'Not Reqd' in l)
        except StopIteration:
            continue
        s = {}
        for l in L[i + 3:]:
            p = l.split()
            if not p or not (p[0].isdigit() and len(p[0]) == 6):
                if s:
                    break
                continue
            v = float(p[1])
            if v > -99:
                s[int(p[0])] = v / 100
        out[fn[:-4]] = guard(s)
    return out


def french_region(region, daily=False):
    """(mkt, rf) 米ドル建て。region: Developed / Developed_ex_US / Europe / Japan / Asia_Pacific_ex_Japan / North_America / Emerging"""
    nm = f'{region}_3_Factors' + ('_Daily' if daily else '')
    d = french(nm)
    t = next(iter(d))
    mk, rf = d[t]['Mkt-RF'], d[t]['RF']
    keep = (lambda k: k > 9999999) if daily else (lambda k: 99999 < k < 1000000)
    return {k: (mk[k] + rf[k]) / 100 for k in mk if k in rf and keep(k)}, {k: rf[k] / 100 for k in rf if keep(k)}


# ───────────────────────── JKP ─────────────────────────
def jkp(region, key, kind='factor', w='vw_cap'):
    """JKP（Jensen・Kelly・Pedersen）の公開データ。kind='factor' → {YYYYMM: 小数}（予言の向き済みの長短）／
    kind='portfolio' → {'1.0'|'2.0'|'3.0': {YYYYMM: 小数}}（三分位・買いだけの素材）。w: vw_cap / vw / ew。guard 済み"""
    d = 'portfolios/' if kind == 'portfolio' else ''
    url = f'https://jkpfactors-data.s3.amazonaws.com/public/{d}%5B{region}%5D_%5B{key}%5D_%5Bmonthly%5D_%5B{w}%5D.zip'
    z = zipfile.ZipFile(io.BytesIO(cached(f'jkp_{kind}_{region}_{key}_{w}.zip', url)))
    out = {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        m = int(x['date'][:4]) * 100 + int(x['date'][5:7])
        k = x.get('pf') if kind == 'portfolio' else (x.get('name') or 'f')
        try:
            out.setdefault(k, {})[m] = float(x['ret'])
        except (TypeError, ValueError):
            continue
    out = {k: guard(v) for k, v in out.items()}
    return out if kind == 'portfolio' else (out.get(key) or next(iter(out.values()), {}))


# ───────────────────────── Shiller / FRED / Yahoo ─────────────────────────
def shiller():
    """[{m, P, D, E, CPI, GS10, CAPE}]（1871〜）。P は S&P 総合の月平均、D・E は年率。guard 済み（m ≤ SEL_END）"""
    import xlrd
    sh = xlrd.open_workbook(file_contents=cached('shiller_ie_data.xls', 'http://www.econ.yale.edu/~shiller/data/ie_data.xls', 60)).sheet_by_name('Data')
    rows = []
    for i in range(8, sh.nrows):
        r = sh.row_values(i)
        if not isinstance(r[0], float):
            continue
        y = int(r[0]); mo = int(round((r[0] - y) * 100)) or 10
        m = y * 100 + mo
        num = lambda v: v if isinstance(v, float) else None
        rows.append({'m': m, 'P': num(r[1]), 'D': num(r[2]), 'E': num(r[3]), 'CPI': num(r[4]), 'GS10': num(r[6]), 'CAPE': num(r[12])})
    return [x for x in rows if PHASE != 'select' or x['m'] <= SEL_END]


def fred(sid):
    raw = cached(f'fred_{sid}.csv', f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}', 20).decode()
    out = {}
    for row in list(csv.reader(io.StringIO(raw)))[1:]:
        if len(row) < 2 or row[1] in ('.', ''):
            continue
        try:
            out[int(row[0][:4]) * 100 + int(row[0][5:7])] = float(row[1])
        except ValueError:
            continue
    return guard(out)


def yahoo(sym, start_year=1970):
    """{YYYYMM: 月末の adjclose}（配当込みの指数）。guard 済み。取れなければ {}"""
    t0 = int(datetime.datetime(start_year, 1, 1).timestamp())
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={t0}&period2={int(time.time())}&interval=1mo'
    try:
        j = json.loads(cached(f'yh_{sym}.json', url, 5))
        res = j['chart']['result'][0]
    except Exception:
        return {}
    ind = res['indicators']
    ser = (ind.get('adjclose') or [{}])[0].get('adjclose') or ind['quote'][0]['close']
    gmt = (res.get('meta') or {}).get('gmtoffset') or 0
    o = {}
    for t, v in zip(res['timestamp'], ser):
        if v is None:
            continue
        d = datetime.datetime.utcfromtimestamp(t + gmt)
        o[d.year * 100 + d.month] = float(v)
    return guard(o)


# ───────────────────────── 月・系列の道具 ─────────────────────────
def add_months(m, k):
    y, mo = divmod(m, 100)
    t = y * 12 + (mo - 1) + k
    return (t // 12) * 100 + t % 12 + 1


def month_range(a, b):
    out, m = [], a
    while m <= b:
        out.append(m)
        m = add_months(m, 1)
    return out


def px_to_ret(px):
    ks = sorted(px)
    return {b: px[b] / px[a] - 1 for a, b in zip(ks, ks[1:]) if add_months(a, 1) == b and px[a] > 0}


def to_monthly(daily):
    out = {}
    for k in sorted(daily):
        m = k // 100
        out[m] = (1 + out.get(m, 0.0)) * (1 + daily[k]) - 1
    return out


def lev_daily(r, rf, L, spread=0.004, fee=0.009, days=252):
    """毎日リセットの L 倍。借りた分 (L−1) に rf＋spread（年率）を払い、経費 fee（年率）を毎日引く。1倍なら素通し"""
    if L == 1:
        return dict(r)
    out = {}
    for k, x in r.items():
        f = rf.get(k, 0.0)
        out[k] = L * x - (L - 1) * (f + spread / days) - fee / days
    return out


def cagr(ret, a=None, b=None):
    ms = [m for m in sorted(ret) if (a is None or m >= a) and (b is None or m <= b)]
    if not ms:
        return None
    g = math.prod(1 + ret[m] for m in ms)
    return g ** (12 / len(ms)) - 1 if g > 0 else -1.0


def maxdd(ret, ms):
    v = peak = 1.0
    dd = 0.0
    for m in ms:
        v *= 1 + ret[m]
        peak = max(peak, v)
        dd = min(dd, v / peak - 1)
    return dd


def stats(ret, bench, rf=None, a=None, b=None, turnover=None, cost=0.0):
    """ret・bench: {YYYYMM: 小数}。共通の月だけで比べる。turnover: {YYYYMM: 片道の回転(1=100%)} × cost を引く。
    → 年率・超過（幾何）・算術超過の t・ぶれ・最大下落・シャープ・転がる10年の勝率"""
    ms = [m for m in sorted(set(ret) & set(bench)) if (a is None or m >= a) and (b is None or m <= b)]
    if len(ms) < 24:
        return None
    net = {m: ret[m] - (turnover.get(m, 0.0) * cost if turnover else 0.0) for m in ms}
    ex = [net[m] - bench[m] for m in ms]
    n = len(ms)
    mu, sd = S.mean(ex), S.stdev(ex)
    t = mu / (sd / math.sqrt(n)) if sd > 0 else None
    # Newey-West（12か月）
    lag = 12
    g0 = sum((x - mu) ** 2 for x in ex) / n
    nw = g0
    for l in range(1, lag + 1):
        gl = sum((ex[i] - mu) * (ex[i - l] - mu) for i in range(l, n)) / n
        nw += 2 * (1 - l / (lag + 1)) * gl
    t_nw = mu / math.sqrt(nw / n) if nw > 0 else None
    cs, cb = cagr(net, ms[0], ms[-1]), cagr(bench, ms[0], ms[-1])
    vol = S.stdev(net[m] for m in ms) * math.sqrt(12)
    volb = S.stdev(bench[m] for m in ms) * math.sqrt(12)
    rfm = rf or {}
    sh = (S.mean(net[m] - rfm.get(m, 0.0) for m in ms) * 12) / vol if vol > 0 else None
    shb = (S.mean(bench[m] - rfm.get(m, 0.0) for m in ms) * 12) / volb if volb > 0 else None
    wins = tot = 0
    for i in range(0, n - 119, 12):                   # 転がる10年（年刻み）
        w = ms[i:i + 120]
        if len(w) < 120:
            break
        tot += 1
        wins += cagr(net, w[0], w[-1]) > cagr(bench, w[0], w[-1])
    return {'from': ms[0], 'to': ms[-1], 'years': round(n / 12, 1),
            'cagr': round(cs * 100, 2), 'bench_cagr': round(cb * 100, 2), 'excess': round((cs - cb) * 100, 2),
            'ex_arith': round(mu * 1200, 2), 't': round(t, 2) if t is not None else None, 't_nw': round(t_nw, 2) if t_nw is not None else None,
            'vol': round(vol * 100, 1), 'bench_vol': round(volb * 100, 1),
            'maxdd': round(maxdd(net, ms) * 100, 1), 'bench_maxdd': round(maxdd(bench, ms) * 100, 1),
            'sharpe': round(sh, 2) if sh is not None else None, 'bench_sharpe': round(shb, 2) if shb is not None else None,
            'roll10_win': f'{wins}/{tot}' if tot else None}


def pnorm_upper(t):
    """片側 p（正規近似）"""
    return 0.5 * math.erfc(t / math.sqrt(2)) if t is not None else 1.0


def save_spec(key, spec, rationale, n_variants, selection_stats, extra=None):
    """選定の段の最後に一度だけ呼ぶ（凍結）。out/edge/spec_{key}.json"""
    assert PHASE == 'select', '凍結は選定の段でだけ行う'
    os.makedirs(os.path.join(BASE, 'out', 'edge'), exist_ok=True)
    doc = {'key': key, 'frozen': datetime.date.today().isoformat(), 'phase': PHASE, 'sel_end': SEL_END,
           'spec': spec, 'rationale': rationale, 'n_variants_tried': n_variants, 'selection_stats': selection_stats}
    if extra:
        doc.update(extra)
    json.dump(doc, open(os.path.join(BASE, 'out', 'edge', f'spec_{key}.json'), 'w'), ensure_ascii=False, indent=1)
    return doc
