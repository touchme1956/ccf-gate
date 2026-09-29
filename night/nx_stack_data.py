#!/usr/bin/env python3
"""night/nx_stack_data.py — 角度 nx_stack（リターンの積み重ね）のデータを取って揃えるだけの道具（成績は計算しない）

事前登録: out/nx_stack_prereg.json（測る前に書いた）。この道具は
  - 出典から取得（キャッシュ out/_nx_cache/・gitignore）
  - 月次リターン {yyyymm: 小数} へ揃える（指数の水準は水準比でリターンへ）
  - out/_nx_cache/nx_stack_series.json に全系列を置く（測る道具 night/nx_stack.py が読む）
  - 形だけを表示する: 始まり・終わり・月数・途中の欠け・ちょうど0の数・原本の sha1
平均・t・シャープ・累積・勝率は**計算しない・表示しない**（事前登録の約束）。

出典
  AQR Century of Factor Premia（1926-07〜）・Time Series Momentum（1985-01〜）・Value and Momentum Everywhere（1972〜）・
  Betting Against Beta（1930-12〜）・Commodities for the Long Run（1877-02〜・名前は水準だが中身は月次リターン）・Credit Risk Premium（1926〜2014）
  CBOE PUT / BXM（日次の水準・実質 2007〜 / 2002〜）
  Shiller ie_data.xls（1871〜・月平均の株価と年率の配当 → 名目の総リターン。1926年より前の独立の時代の土台だけに使う）
  Ken French 3因子（Mkt = Mkt-RF + RF、RF）
  Yahoo（実在のファンドの答え合わせ用・生き残りの偏りあり）
"""
import sys, os, io, json, hashlib, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N

OUT = os.path.join(N.CACHE, 'nx_stack_series.json')
SHILLER = 'http://www.econ.yale.edu/~shiller/data/ie_data.xls'
CBOE = 'https://cdn.cboe.com/api/global/us_indices/daily_prices/{}_History.csv'
FUNDS = ['AQMIX', 'QMHIX', 'QSPIX', 'QRPRX', 'ASFYX', 'PQTIX', 'DBMF', 'KMLM', 'CTA', 'RSST', 'RSSB', 'RSBT', 'RSSY',
         'NTSX', 'GDE', 'COM', 'HYZD', 'DBC', 'GSG', 'PUTW', 'SPY']


def sha1(b):
    return hashlib.sha1(b).hexdigest()[:12]


def _ym(d):
    if isinstance(d, (datetime.datetime, datetime.date)):
        return d.year * 100 + d.month
    s = str(d).strip()
    if '/' in s:
        mm, dd, yy = s.split('/')
        return int(yy) * 100 + int(mm)
    if '-' in s and len(s) >= 7:
        return int(s[:4]) * 100 + int(s[5:7])
    return None


def aqr_generic(dataset, sheet, header_pred, levels=False):
    """AQR の xlsx の1枚を読む。header_pred(row) が真の行を見出しとし、その下の日付つきの行を取る。
    levels=True なら水準 → 月次リターン（水準比）。見出しの先頭セルが空の表（TSMOM・CLR）にも使える"""
    import openpyxl
    b = N.get(N.AQR.format(dataset), name=f'aqr_{dataset}.xlsx')
    wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
    cols, raw = None, {}
    for row in wb[sheet].iter_rows(values_only=True):
        if cols is None:
            if header_pred(row):
                cols = [str(c).strip() if c is not None else '' for c in row]
                raw = {c: {} for c in cols[1:] if c}
            continue
        ym = _ym(row[0]) if row and row[0] is not None else None
        if ym is None:
            continue
        for c, v in zip(cols[1:], row[1:]):
            if not c or v is None or isinstance(v, str):
                continue
            try:
                x = float(v)
            except (TypeError, ValueError):
                continue
            if x != x:
                continue
            raw[c][ym] = x
    if not levels:
        return raw, sha1(b)
    out = {}
    for c, s in raw.items():
        ks = sorted(s)
        out[c] = {k: s[k] / s[p] - 1 for p, k in zip(ks, ks[1:]) if s[p] and _next(p) == k}
    return out, sha1(b)


def _next(ym):
    y, m = divmod(ym, 100)
    return (y + 1) * 100 + 1 if m == 12 else ym + 1


def cboe(name):
    b = N.get(CBOE.format(name), name=f'cboe_{name}.csv', max_age_days=7)
    px = {}
    for line in b.decode(errors='ignore').splitlines()[1:]:
        p = line.split(',')
        if len(p) < 2:
            continue
        try:
            mm, dd, yy = p[0].split('/'); v = float(p[1])
        except ValueError:
            continue
        px[int(yy) * 10000 + int(mm) * 100 + int(dd)] = v
    last = {}
    for k in sorted(px):  # 月末（その月の最後の取引日）の水準
        last[k // 100] = px[k]
    ks = sorted(last)
    # 取引日が月に15日未満の月（早い年の飛び飛びの点）はリターンを作らない
    days = {}
    for k in px:
        days[k // 100] = days.get(k // 100, 0) + 1
    good = [k for k in ks if days[k] >= 15]
    return {k: last[k] / last[p] - 1 for p, k in zip(good, good[1:]) if _next(p) == k}, sha1(b)


def shiller_nominal_tr():
    """Shiller ie_data.xls: 名目の総リターン = (P_t + D_t/12) / P_{t-1} − 1（P は月平均・D は年率の配当）"""
    import xlrd
    b = N.get(SHILLER, name='shiller_ie_data.xls', max_age_days=60)
    sh = xlrd.open_workbook(file_contents=b).sheet_by_name('Data')
    rows = []
    for i in range(sh.nrows):
        r = sh.row_values(i)
        if not isinstance(r[0], float) or not isinstance(r[1], float) or not isinstance(r[2], float):
            continue
        y = int(r[0]); m = int(round((r[0] - y) * 100))
        if not 1 <= m <= 12:
            continue
        rows.append((y * 100 + m, r[1], r[2]))
    out = {}
    for (p, pp, _), (k, pk, dk) in zip(rows, rows[1:]):
        if _next(p) == k and pp:
            out[k] = (pk + dk / 12) / pp - 1
    return out, sha1(b)


def shape(s):
    ks = sorted(s)
    if not ks:
        return None
    a, z = ks[0], ks[-1]
    n_exp = (z // 100 - a // 100) * 12 + (z % 100 - a % 100) + 1
    return {'from': a, 'to': z, 'n': len(ks), 'gaps': n_exp - len(ks), 'exact_zero': sum(1 for v in s.values() if v == 0.0)}


def main():
    series, src = {}, {}
    ff = N.ff_factors()
    series['FF|Mkt'] = ff['mkt']; series['FF|RF'] = ff['rf']; series['FF|MktRF'] = ff['mktrf']
    src['FF'] = N.FR.format('F-F_Research_Data_Factors')

    d, h = aqr_generic('Century-of-Factor-Premia-Monthly', 'Century of Factor Premia',
                       lambda r: r and r[0] is not None and str(r[0]).strip() == 'Date')
    for c, s in d.items():
        series['CFP|' + c] = s
    src['CFP'] = h
    d, h = aqr_generic('Time-Series-Momentum-Factors-Monthly', 'TSMOM Factors',
                       lambda r: r and len(r) > 1 and r[1] is not None and str(r[1]).strip() == 'TSMOM')
    for c, s in d.items():
        series['TSMOM|' + c] = s
    src['TSMOM'] = h
    d, h = aqr_generic('Value-and-Momentum-Everywhere-Factors-Monthly', 'VME Factors',
                       lambda r: r and r[0] is not None and str(r[0]).strip() == 'DATE')
    for c in ('VAL', 'MOM', 'VAL^AA', 'MOM^AA', 'VAL^SS', 'MOM^SS', 'VALLS_VME_EQ', 'MOMLS_VME_EQ', 'VALLS_VME_FX',
              'MOMLS_VME_FX', 'VALLS_VME_FI', 'MOMLS_VME_FI', 'VALLS_VME_COM', 'MOMLS_VME_COM'):
        if c in d:
            series['VME|' + c] = d[c]
    src['VME'] = h
    d, h = aqr_generic('Betting-Against-Beta-Equity-Factors-Monthly', 'BAB Factors',
                       lambda r: r and r[0] is not None and str(r[0]).strip() == 'DATE')
    for c in ('USA', 'Global', 'Global Ex USA'):
        series['BAB|' + c] = d[c]
    src['BAB'] = h
    d, h = aqr_generic('Commodities-for-the-Long-Run-Index-Level-Data-Monthly', 'Commodities for the Long Run',
                       lambda r: r and len(r) > 1 and r[1] is not None and str(r[1]).startswith('Excess return of equal-weight'))
    # ⚠ データ集の名前は『Index Level Data』だが、中身は**月次リターン（小数）**だった（形で確認: 負の値がある・|x|>0.5 が0件・
    #   1か月ずれの自己相関 0.13 / 0.05＝水準や対数水準なら 1 に近い）。水準として割るとでたらめになるので、そのまま使う
    series['CLR|EW_excess'] = d['Excess return of equal-weight commodities portfolio']
    series['CLR|LS_excess'] = d['Excess return of long/short commodities portfolio']
    src['CLR'] = h
    d, h = aqr_generic('Credit-Risk-Premium-Preliminary-Paper-Data', 'Credit Risk Premium',
                       lambda r: r and r[0] is not None and str(r[0]).strip() == 'Date')
    for c in ('CORP_XS', 'GOVT_XS', 'SP500_XS'):
        series['CRP|' + c] = d[c]
    src['CRP'] = h
    for nm in ('PUT', 'BXM'):
        s, h = cboe(nm)
        series['CBOE|' + nm] = s; src['CBOE_' + nm] = h
    s, h = shiller_nominal_tr()
    series['SHILLER|nominal_TR'] = s; src['SHILLER'] = h
    for t in FUNDS:
        try:
            series['YH|' + t] = N.yahoo(t)
        except Exception as e:  # noqa
            print('Yahoo 取得失敗', t, e)

    json.dump({'generated': datetime.date.today().isoformat(), 'sha1': src,
               'series': {k: {str(m): v for m, v in s.items()} for k, s in series.items()}},
              open(OUT, 'w'))
    print('書いた:', OUT)
    for k, s in series.items():
        print(f'{k:48s}', shape(s))
    print('原本の sha1:', src)


def load():
    """測る道具が使う読み手 → {名前: {yyyymm(int): 小数}}"""
    j = json.load(open(OUT))
    return {k: {int(m): v for m, v in s.items()} for k, s in j['series'].items()}, j


if __name__ == '__main__':
    main()
