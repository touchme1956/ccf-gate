#!/usr/bin/env python3
"""night/gaps_common.py — 歴史検証の穴7つ（out/gaps7_prereg.json）で共有する部品（読むだけ・判定に不使用）

  fred(id)         … FRED の系列（月次にそろえる: 日次は各月の最後の値・月次はそのまま）
  french_mkt()     … Ken French の米国市場（Mkt-RF+RF）・RF（月次・小数）
  french_country() … 国別の Value-Weight Local / Dollar Returns（Mkt 列・配当込み・月次・小数）
  french_tech()    … 49業種の Hardw・Softw・Chips を前月末の時価総額で加重した合成（月次・小数）
  dca(rets, ...)   … 毎月同額の積立の倍率と資金加重の年率（IRR）
キャッシュは out/_gaps_cache/（repo に入れない）
"""
import io, json, math, os, sys, time, urllib.request, zipfile, csv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
CACHE = os.path.join(BASE, 'out', '_gaps_cache')
FR = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{}'
UA = {'User-Agent': 'Mozilla/5.0 (ccf-gate research)'}


def _get(url, tries=4, timeout=120):
    # FRED はブラウザ風の User-Agent を切断する（実測 2026-09-28）。curl の名乗りなら通る
    hd = {'User-Agent': 'curl/8.5.0'} if 'stlouisfed.org' in url else UA
    for a in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=hd), timeout=timeout).read()
        except Exception:
            if a == tries - 1:
                raise
            time.sleep(4 * (a + 1))


def _cached(name, url, days=20):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < days * 86400 and os.path.getsize(p) > 100:
        return open(p, 'rb').read()
    b = _get(url)
    open(p + '.part', 'wb').write(b)
    os.replace(p + '.part', p)
    return b


def fred(sid):
    """{YYYYMM: 値}。日次の系列は各月の最後の観測値、月次はそのまま。欠測（'.'）は捨てる"""
    raw = _cached(f'fred_{sid}.csv', f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}').decode()
    out = {}
    for row in list(csv.reader(io.StringIO(raw)))[1:]:
        if len(row) < 2 or row[1] in ('.', ''):
            continue
        d = row[0]
        try:
            out[int(d[:4]) * 100 + int(d[5:7])] = float(row[1])   # 同じ月の後の観測で上書き＝月末の値
        except ValueError:
            continue
    return out


def _lines(zipname):
    z = zipfile.ZipFile(io.BytesIO(_cached(zipname, FR.format(zipname))))
    return z, z.namelist()


def french_mkt():
    """米国市場の月次リターン（Mkt-RF+RF）と RF（小数）"""
    z, names = _lines('F-F_Research_Data_Factors_CSV.zip')
    L = z.read(names[0]).decode('latin-1').split('\n')
    i = next(k for k, l in enumerate(L) if l.strip().startswith(',') and 'Mkt-RF' in l)
    mkt, rf = {}, {}
    for l in L[i + 1:]:
        p = [x.strip() for x in l.split(',')]
        if len(p) < 5 or not (p[0].isdigit() and len(p[0]) == 6):
            break
        m = int(p[0])
        mkt[m] = (float(p[1]) + float(p[4])) / 100
        rf[m] = float(p[4]) / 100
    return mkt, rf


def french_country(name, currency='Local'):
    """国別（'Japan' 等）の Value-Weight {currency} Returns・All 4 Data Items Not Reqd の Mkt 列"""
    z, names = _lines('F-F_International_Countries.zip')
    fn = next(n for n in names if n.lower().startswith(name.lower()))
    L = z.read(fn).decode('latin-1').split('\n')
    head = f'Value-Weight {currency}'
    i = next(k for k, l in enumerate(L) if head in l and 'Not Reqd' in l)
    out = {}
    for l in L[i + 3:]:
        p = l.split()
        if not p or not (p[0].isdigit() and len(p[0]) == 6):
            if out:
                break
            continue
        v = float(p[1])
        if v > -99:
            out[int(p[0])] = v / 100
    return out


def french_countries():
    z, names = _lines('F-F_International_Countries.zip')
    return [n[:-4] for n in names if n.lower().endswith('.dat')]


def french_tech():
    """Hardw・Softw・Chips を前月末の時価総額（社数×平均時価総額）で加重した月次リターン"""
    from industry_long import lines, block
    L = lines('49_Industry_Portfolios')
    ret = block(L, 'Average Value Weighted Returns -- Monthly')
    nf = block(L, 'Number of Firms in Portfolios')
    sz = block(L, 'Average Firm Size')
    out = {}
    ks = ('Hardw', 'Softw', 'Chips')
    months = sorted(set().union(*[set(ret[k]) for k in ks]))
    for m in months:
        num = den = 0.0
        for k in ks:
            r = ret[k].get(m)
            w = (nf[k].get(m) or 0) * (sz[k].get(m) or 0)   # French の平均時価総額は組入れ時点（前月末）の値
            if r is None or w <= 0:
                continue
            num += w * r / 100
            den += w
        if den > 0:
            out[m] = num / den
    return out


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


def irr_monthly(flows):
    """flows: 月ごとの現金の流れ（投資はマイナス・最後の評価額はプラス）→ 年率。二分法"""
    def npv(r):
        return sum(f / (1 + r) ** i for i, f in enumerate(flows))
    lo, hi = -0.2, 0.2          # 月率 ±20%（年率 −93%〜+792%）の中に必ず収まる
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (1 + (lo + hi) / 2) ** 12 - 1


def dca(rets, start, n, irr=False):
    """rets: {YYYYMM: 月次リターン}。start の月の初めに1、以後毎月初めに1を入れ、n か月後の月末に評価。
    → (倍率, 年率)。年率は irr=True のときだけ計算（重いので）。途中の月が欠けていたら None"""
    months = [add_months(start, i) for i in range(n)]
    if any(m not in rets for m in months):
        return None, None
    v = 0.0
    for m in months:
        v = (v + 1) * (1 + rets[m])
    if not irr:
        return v / n, None
    flows = [-1.0] * n + [0.0]
    flows[-1] += v
    return v / n, irr_monthly(flows)
