#!/usr/bin/env python3
"""night/bestpf_tech12.py — 楽天・テック12（Solactive・米国超大型テクノロジー株式12指数）を株ごとのデータから組み直す（2026-10-12・ユーザー「NDX40/SMH25/ITA10/楽天テック12 10/個別15は？」）

読むだけ。門・採点・配分には触れない。事前登録の外（ユーザーの問いへの答えのための代用づくり）。

なぜ組み直すか: この指数は 2026年に作られ、公開の月次の系列が無い（交付目論見書 p.9 に暦年の騰落率 2017〜2026年5月だけ）。
NASDAQ-100（QQQ）で代えると、配合の NDX40 と同じ系列を足すだけになり、上位7社に84%を置く集中の効果が消える。

指数の決まり（交付目論見書 ritech12_P.pdf p.2〜3）:
  母集団 = Solactive United States Technology 100（NASDAQ 上場の米国企業・金融を除く時価総額上位100）
  年4回の見直しで「テクノロジー関連企業」を抜き出し、時価総額の上位12社。見直し時に上位7社 各12%（計84%）・残り5社 各3.2%（計16%）。
  大型 IPO は臨時に入れる（SpaceX は 2026-06-12 の上場後に入った）。
組み直し:
  - 見直しは 3・6・9・12月の月末の時価総額で選び、その翌月から持つ（四半期の中は値動きで重みが漂う＝買って持つ）
  - 時価総額 = 株数（SEC companyfacts の dei:EntityCommonStockSharesOutstanding〔表紙の株数・その時点で提出済みの最新〕、
    無ければ us-gaap:WeightedAverageNumberOfSharesOutstandingBasic）を今の分割の基準へ直したもの × Yahoo の分割調整済みの終値
  - 月のリターン = Yahoo の調整後終値（配当込み・源泉税は引かない）。価格が取れない月の構成銘柄は、残りの構成銘柄の重みで按分（0 と読まない）
  - 「テクノロジー関連」の範囲は目論見書に書かれていないので、候補の群（情報技術・ネット〔GOOGL/META/AMZN/EBAY〕・EV〔TSLA〕・メディア〔NFLX など〕・宇宙〔SpaceX〕）の
    入れ方を変えた版を作り、目論見書の暦年の騰落率（円）に最も近い版を主にする（版の選び方は答え合わせの当てはめ＝結果を見た選択であることを記録する）
  - 2010年より前は株数の XBRL が無く、当時の上位（Sun・JDSU・Yahoo・Broadcom 旧社 など）の価格も Yahoo に無いので組み直さない
    （bestpf_check では 2000-09〜2009-12 を NASDAQ-100 で埋めた版を使い、その限界を名指しする）
出力: out/bestpf_tech12.json（月次のドル建ての配当込みリターン・構成銘柄の履歴・答え合わせ）
"""
import datetime, json, math, os, sys, time, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import mw_common as MW                                  # noqa: E402
from mw_best_ideas_13f import SEC_UA                    # noqa: E402

OUT = os.path.join(BASE, 'out', 'bestpf_tech12.json')
CDIR = os.path.join(BASE, 'out', '_bestpf_cache', 'tech12')
FX_CSV = os.path.join(BASE, 'out', '_gaps_cache', 'fred_DEXJPUS.csv')
START, END = 200912, 202609          # 最初の見直し 2009-12 → 2010-01 から持つ

# 目論見書 p.9 の暦年の騰落率（配当込み・円換算）。2026 は 5月末まで
OFFICIAL_YEN = {2017: 29.1, 2018: 0.2, 2019: 39.9, 2020: 45.0, 2021: 65.5, 2022: -38.4, 2023: 111.2,
                2024: 74.9, 2025: 22.1, 2026: 20.9}

# 候補: ticker → (Yahoo, [CIK…], 群, NASDAQ に居た月の範囲 (from, to)・None は制限なし, 米国企業の範囲)
# 群: it=情報技術 / net=ネット（検索・SNS・ネット通販）/ ev=EV / media=メディア・通信・娯楽 / space=宇宙
U = {
    'AAPL': ('AAPL', [320193], 'it', None),
    'MSFT': ('MSFT', [789019], 'it', None),
    'NVDA': ('NVDA', [1045810], 'it', None),
    'AVGO': ('AVGO', [1730168, 1671933, 1441634], 'it', None),
    'INTC': ('INTC', [50863], 'it', None),
    'CSCO': ('CSCO', [858877], 'it', None),
    'QCOM': ('QCOM', [804328], 'it', None),
    'ORCL': ('ORCL', [1341439], 'it', (None, 201306)),       # 2013-07-15 に NYSE へ
    'ADBE': ('ADBE', [796343], 'it', None),
    'TXN': ('TXN', [97476], 'it', (201201, None)),           # 2012-01-03 に NASDAQ へ（8-K 2011-12-15）
    'AMAT': ('AMAT', [6951], 'it', None),
    'INTU': ('INTU', [896878], 'it', None),
    'AMD': ('AMD', [2488], 'it', None),
    'MU': ('MU', [723125], 'it', None),
    'LRCX': ('LRCX', [707549], 'it', None),
    'KLAC': ('KLAC', [319201], 'it', None),
    'ADI': ('ADI', [6281], 'it', None),
    'CTSH': ('CTSH', [1058290], 'it', None),
    'ADP': ('ADP', [8670], 'it', (None, 202302)),            # GICS で情報技術だった間だけ（2023-03 に資本財へ）
    'SNPS': ('SNPS', [883241], 'it', None),
    'CDNS': ('CDNS', [813672], 'it', None),
    'PYPL': ('PYPL', [1633917], 'it', None),
    'MRVL': ('MRVL', [1835632, 1058057], 'it', None),
    'PANW': ('PANW', [1327567], 'it', (202109, None)),       # 2021-08 に NYSE から NASDAQ へ
    'CRWD': ('CRWD', [1535527], 'it', None),
    'PLTR': ('PLTR', [1321655], 'it', (202412, None)),       # 2024-11-26 に NYSE から NASDAQ へ
    'APP': ('APP', [1751008], 'it', None),
    'MSTR': ('MSTR', [1050446], 'it', None),
    'DELL_OLD': (None, [826083], 'it', (None, 201309)),      # 旧 Dell（2013-10 に非公開化・Yahoo に価格なし）
    'BRCM': (None, [1054374], 'it', (None, 201512)),         # 旧 Broadcom（2016-02 に Avago と統合・Yahoo に価格なし）
    'YHOO': (None, [1011006], 'net', (None, 201703)),        # Yahoo（2017-06 に Altaba・Yahoo に価格なし）
    'GOOGL': ('GOOGL', [1652044, 1288776], 'net', None),
    'META': ('META', [1326801], 'net', None),
    'AMZN': ('AMZN', [1018724], 'net', None),
    'EBAY': ('EBAY', [1065088], 'net', None),
    'TSLA': ('TSLA', [1318605], 'ev', None),
    'NFLX': ('NFLX', [1065280], 'media', None),
    'CMCSA': ('CMCSA', [1166691], 'media', None),
    'TMUS': ('TMUS', [1283699], 'media', None),
    'SPCX': ('SPCX', [1181412], 'space', None),
}
VARIANTS = {
    'it+net+space': {'it', 'net', 'space'},
    'it+net+space+ev': {'it', 'net', 'space', 'ev'},
    'it+net+space+ev+media': {'it', 'net', 'space', 'ev', 'media'},
    'it+net+space+media': {'it', 'net', 'space', 'media'},
    # 2026年9月の組み入れ（第三者の記事・上位10社）に TSLA が無い（時価総額では8位に入るはず）＝今は「テクノロジー関連」の外。
    # 一方 2020〜2022年の目論見書の値は TSLA を入れた版にしか近づかない → 2026-06 の見直しから TSLA を外す版（当てはめ）
    'it+net+space+ev+media→2026-06からTSLA除く': ({'it', 'net', 'space', 'ev', 'media'}, {'it', 'net', 'space', 'media'}, 202606),
}


def groups_at(g, m):
    if isinstance(g, tuple):
        return g[0] if m < g[2] else g[1]
    return g


def ym_add(m, k):
    y, mm = divmod(m // 100 * 12 + m % 100 - 1 + k, 12)
    return y * 100 + mm + 1


def months(a, b):
    out, m = [], a
    while m <= b:
        out.append(m); m = ym_add(m, 1)
    return out


def sec_json(cik):
    os.makedirs(CDIR, exist_ok=True)
    p = os.path.join(CDIR, f'cf_{cik}.json')
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 20 * 86400:
        return json.load(open(p))
    url = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json'
    for i in range(5):
        try:
            import gzip
            b = urllib.request.urlopen(urllib.request.Request(url, headers=SEC_UA), timeout=120).read()
            try:
                b = gzip.decompress(b)
            except OSError:
                pass
            j = json.loads(b)
            json.dump(j, open(p, 'w'))
            time.sleep(0.15)
            return j
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 * (i + 1))
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def share_obs(ciks):
    """[(filed 'YYYY-MM-DD', 株数, 種類)] を提出日の順に。dei の表紙の株数（同じ受付番号の種類別を足す）を先に、無い提出は加重平均の基本株数"""
    obs = []
    for cik in ciks:
        j = sec_json(cik)
        if not j:
            continue
        f = j.get('facts', {})
        dei = f.get('dei', {}).get('EntityCommonStockSharesOutstanding', {}).get('units', {}).get('shares', [])
        by = {}
        for x in dei:
            k = x['accn']
            by.setdefault(k, {'filed': x['filed'], 'end': x['end'], 'v': 0.0, 'n': 0})
            by[k]['v'] += x['val']; by[k]['n'] += 1
        for k, v in by.items():
            if v['v'] > 0:
                obs.append((v['filed'], v['v'], 'dei', v['end']))
        done = set(by)
        # 表紙の株数が種類ごと（次元つき）で companyfacts に出ない会社（Alphabet など）は、貸借対照表の発行済株式数、無ければ加重平均の基本株数
        for tag, kind in (('CommonStockSharesOutstanding', 'bs'), ('WeightedAverageNumberOfSharesOutstandingBasic', 'wa')):
            xs = f.get('us-gaap', {}).get(tag, {}).get('units', {}).get('shares', [])
            best = {}
            for x in xs:
                if x['accn'] in done or x.get('form') not in ('10-K', '10-Q', '10-K/A', '10-Q/A', '20-F', '10-KT'):
                    continue
                k = x['accn']
                if k not in best or x['end'] > best[k]['end']:
                    best[k] = x
            for x in best.values():
                obs.append((x['filed'], x['val'], kind, x['end']))
            done |= set(best)
    obs.sort()
    return obs


# companyfacts に合計の株数が無い会社の手入力（出典つき）
HAND_SHARES = {
    'SPCX': [('2026-06-12', 7696293669 + 5485486276, 'hand', '2026-07-28')],   # 10-Q（2026-08-04 提出・受付番号 0001628280-26-052535）の表紙: Class A 7,696,293,669 ＋ Class B 5,485,486,276
}


def clean_obs(obs, splits):
    """株数の桁の誤り（実測: QCOM 2011年の表紙の株数が1000倍）を落とす。今の分割の基準へ直した値が、前後3年の観測の中央値の 0.4〜2.5倍の外なら捨てる"""
    def today(o):
        fac = 1.0
        for sd, r in splits:
            if sd > o[0]:
                fac *= r
        return o[1] * fac
    vals = [(datetime.date.fromisoformat(o[0]), today(o)) for o in obs]
    keep = []
    for o, (d, v) in zip(obs, vals):
        near = sorted(x for dd, x in vals if abs((dd - d).days) <= 1100)
        med = near[len(near) // 2]
        if 0.4 <= v / med <= 2.5:
            keep.append(o)
    return keep


def yahoo_full(t):
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{t}?period1=1230768000&period2={int(time.time())}&interval=1mo&events=div%2Csplit'
    try:
        j = json.loads(MW.get(u, name=f'yh_{t}_1mo_full.json', max_age_days=3))
    except Exception as e:
        print('  Yahoo 失敗', t, e)
        return None
    r = (j.get('chart') or {}).get('result')
    if not r:
        return None
    r = r[0]
    off = r.get('meta', {}).get('gmtoffset') or 0
    ts = r.get('timestamp') or []
    q = r['indicators']['quote'][0]
    adj = (r['indicators'].get('adjclose') or [{}])[0].get('adjclose') or q['close']
    close, adjc = {}, {}
    now = datetime.datetime.utcfromtimestamp(time.time() + off)
    cur = now.year * 100 + now.month
    for t_, c, a in zip(ts, q['close'], adj):
        d = datetime.datetime.utcfromtimestamp(t_ + off)
        k = d.year * 100 + d.month
        if k >= cur or c is None or a is None:
            continue
        close[k], adjc[k] = c, a
    splits = []
    for v in ((r.get('events') or {}).get('splits') or {}).values():
        d = datetime.datetime.utcfromtimestamp(v['date'] + off).strftime('%Y-%m-%d')
        splits.append((d, v['numerator'] / v['denominator']))
    splits.sort()
    ks = sorted(adjc)
    ret = {k: adjc[k] / adjc[p] - 1 for p, k in zip(ks, ks[1:]) if ym_add(p, 1) == k}
    return dict(close=close, ret=ret, splits=splits)


def month_end_str(m):
    y, mm = divmod(m, 100)
    nxt = datetime.date(y + (mm == 12), mm % 12 + 1, 1)
    return (nxt - datetime.timedelta(days=1)).isoformat()


def mcap_at(m, obs, yh):
    """m の月末の時価総額（ドル）。株数はその日までに提出された最新・今の分割の基準へ直す"""
    if yh is None or m not in yh['close']:
        return None
    d = month_end_str(m)
    cand = [o for o in obs if o[0] <= d]
    if not cand:
        return None
    filed, sh, kind, end = cand[-1]
    if (datetime.date.fromisoformat(d) - datetime.date.fromisoformat(end)).days > 400:
        return None            # 1年以上古い株数は使わない
    fac = 1.0
    for sd, r in yh['splits']:
        if sd > filed:
            fac *= r
    return sh * fac * yh['close'][m]


def listed(meta, m):
    w = meta[3]
    if w is None:
        return True
    a, b = w
    return (a is None or m >= a) and (b is None or m <= b)


def fx_month_end():
    """FRED DEXJPUS の日次 → 月末の円/ドル"""
    out = {}
    for line in open(FX_CSV):
        p = line.strip().split(',')
        if len(p) < 2 or not p[0][:4].isdigit():
            continue
        try:
            v = float(p[1])
        except ValueError:
            continue
        k = int(p[0][:4]) * 100 + int(p[0][5:7])
        out[k] = v            # 日付の順なので最後が月末
    return out


def build(groups, data, mc):
    """月次のドル建てリターンと構成銘柄の履歴"""
    rets, hist, w = {}, {}, None
    for m in months(START, END):
        if w is not None:
            num = den = 0.0
            for t, wt in w.items():
                r = data[t]['yh']['ret'].get(m) if data[t]['yh'] else None
                if r is not None:
                    num += wt * r; den += wt
            if den > 0:
                rp = num / den
                rets[m] = rp
                # 漂い: 取れない銘柄は平均で動いたとみなす
                nw = {}
                for t, wt in w.items():
                    r = data[t]['yh']['ret'].get(m) if data[t]['yh'] else None
                    nw[t] = wt * (1 + (r if r is not None else rp))
                s = sum(nw.values())
                w = {t: v / s for t, v in nw.items()}
        if m % 100 in (3, 6, 9, 12) or w is None:
            elig = [(mc[t].get(m), t) for t in U if U[t][2] in groups_at(groups, m) and listed(U[t], m) and mc[t].get(m)]
            elig.sort(reverse=True)
            top = elig[:12]
            if len(top) < 12:
                print('  ⚠ 候補が12社に満たない', m, len(top))
            w = {t: (0.12 if i < 7 else 0.032) for i, (_, t) in enumerate(top)}
            s = sum(w.values()); w = {t: v / s for t, v in w.items()}
            hist[m] = [(t, round(v / 1e9, 1)) for v, t in top]
    return rets, hist


def yen_years(rets, fx, years):
    out = {}
    for y in years:
        a, b = y * 100 + 1, (y * 100 + 12 if y < 2026 else 202605)
        ms = [m for m in months(a, b)]
        if not all(m in rets for m in ms):
            continue
        g = 1.0
        for m in ms:
            g *= 1 + rets[m]
        fx0, fx1 = fx.get(ym_add(a, -1)), fx.get(b)
        out[y] = round(100 * (g * fx1 / fx0 - 1), 1)
    return out


HOLD_2026_09 = [('MSFT', 14.96), ('NVDA', 12.46), ('AAPL', 12.14), ('AMZN', 12.04), ('SPCX', 11.64), ('AVGO', 10.81), ('GOOGL', 10.70),
                ('META', 3.32), ('MU', 3.20), ('AMD', 3.02), ('INTC', 2.85), ('AMAT', 2.85)]   # 上位10社は第三者の記事（2026年9月）・11〜12位は組み直しの 2026-06 の見直し（INTC・AMAT）で残りの 5.71% を等分
FEE = 0.00462        # 信託報酬（税込）
DY = 0.0035          # 配当利回りの置き値（超大型テックの中心）。NISA でも米国の源泉税10%は戻らない
TAX_K = 0.10


def compute_worlds():
    """世界 B・C・D を bestpf_ext と同じ式で（保有で重み付けした49業種の上乗せ・記録の二業種の比重・JPM の米国大型株・D は QQQM と同じ総額から費用だけ差し替え）"""
    import etf_forward_rank as R
    import bestpf_ext as X
    bi = X.b_inputs()
    ind_of, sic = X.mapper([t for t, _ in HOLD_2026_09])
    X_ind = bi['X_ind']
    mapped = [(t, ind_of(t), w) for t, w in HOLD_2026_09]
    mw = sum(w for _, k, w in mapped if k)
    e = sum(w for _, k, w in mapped if k in ('Softw', 'Chips')) / mw
    xi = sum(w * X_ind[k]['x'] for _, k, w in mapped if k in X_ind) / mw
    b_gross = R.R_EQ + R.SHRINK * xi + (R.REC_A - R.REC_B * e)
    c_gross = (R.H_JPM * R.JPM['USL'] / 100 + (R.H - R.H_JPM) * b_gross) / R.H
    tax = DY * TAX_K
    cma = json.load(open(os.path.join(BASE, 'out', 'bestpf_cma_2026.json')))['D_net_by_asset']
    q = X.rank_result()['rows']['QQQM']
    d_gross = cma['QQQM'] + q['er_vehicle'] + q['tax_drag']
    return dict(holdings=HOLD_2026_09, industries={t: k for t, k, _ in mapped}, coverage=round(mw / sum(w for _, w in HOLD_2026_09), 3),
                record_share_e=e, X_ind=xi, B_gross=b_gross, C_gross=c_gross, D_gross=d_gross, fee=FEE, dy=DY, tax_drag=tax,
                B=b_gross - FEE - tax, C=c_gross - FEE - tax, D=d_gross - FEE - tax,
                qqqm=dict(B=q['B'], C=q['C'], D=cma['QQQM'], e=q['record_share_e']),
                note='B = 先進国株の名目（UBS 2026）＋0.5×保有で重み付けした49業種の長い上乗せ＋記録の二業種の罰（0.204%−0.52%×e）。'
                     'C = JPM 2026 の米国大型株（12.5年）の後に B。D = QQQM の D（15社の中央値）の総額から費用・税だけ差し替え。超大型株への集中そのものの基礎率（tech_persist）は入れていない＝感度で見る')


def main():
    fx = fx_month_end()
    data = {}
    for t, meta in U.items():
        yh = yahoo_full(meta[0]) if meta[0] else None
        obs = share_obs(meta[1]) + HAND_SHARES.get(t, [])
        obs.sort()
        n0 = len(obs)
        obs = clean_obs(obs, yh['splits'] if yh else [])
        if len(obs) < n0:
            print(f'  {t}: 株数の観測 {n0 - len(obs)} 件を桁の誤りとして捨てた')
        data[t] = dict(yh=yh, obs=obs)
        print(f'  {t:9} 価格 {len(yh["ret"]) if yh else 0:3}か月  株数の観測 {len(obs):3}', flush=True)
    mc = {t: {m: mcap_at(m, data[t]['obs'], data[t]['yh']) for m in months(START, END)} for t in U}
    # 価格の無い3社（旧 Dell・旧 Broadcom・Yahoo）の時価総額は、株数 × 最後に分かる価格が無いので選べない → 名指し
    qqq = MW.yahoo('QQQ')
    yrs = list(OFFICIAL_YEN)
    res = {}
    for vn, g in VARIANTS.items():
        r, h = build(g, data, mc)
        yy = yen_years(r, fx, yrs)
        err = [yy[y] - OFFICIAL_YEN[y] for y in yrs if y in yy]
        rmse = math.sqrt(sum(e * e for e in err) / len(err)) if err else None
        res[vn] = dict(rets=r, hist=h, yen=yy, rmse=rmse)
        print(f'{vn[:26]:26} RMSE {rmse:5.1f}pt  ' + ' '.join(f'{y}:{yy.get(y)}' for y in yrs), flush=True)
    qy = yen_years(qqq, fx, yrs)
    print(f'{"QQQ（同じ計算）":26}            ' + ' '.join(f'{y}:{qy.get(y)}' for y in yrs))
    print(f'{"目論見書":26}            ' + ' '.join(f'{y}:{OFFICIAL_YEN[y]}' for y in yrs))
    best = min(res, key=lambda k: res[k]['rmse'])
    HYB = 'it+net+space+ev+media→2026-06からTSLA除く'
    if res[HYB]['rmse'] <= res[best]['rmse'] + 0.5:
        best = HYB          # 目論見書の暦年に同じくらい近く、2026年9月の実際の上位10社（TSLA なし）とも合う版
    print('主の版:', best)
    for m in sorted(res[best]['hist']):
        if m % 100 == 12 or m >= 202603:
            print('  ', m, res[best]['hist'][m])
    # 2010-01〜 の年率（ドル）と QQQ
    def cagr(rr, a, b):
        ms = months(a, b); g = 1.0
        for m in ms:
            g *= 1 + rr[m]
        return 100 * (g ** (12 / len(ms)) - 1)
    for a, b in [(201001, 202609), (201110, 202609), (201701, 202605)]:
        print(f'  年率（ドル）{a}〜{b}: テック12の組み直し {cagr(res[best]["rets"], a, b):5.1f}%  QQQ {cagr(qqq, a, b):5.1f}%')
    missing_px = [t for t in U if not data[t]['yh']]
    sel_missing = sorted({t for v in res.values() for h in v['hist'].values() for t, _ in h if t in missing_px})
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/bestpf_tech12.py', posthoc=True,
               question='NDX40/SMH25/ITA10/楽天テック12 10/個別15 は？（ユーザーの問い）',
               fund=dict(name='楽天・米国テクノロジー株式集中投資インデックス・ファンド（楽天・テック12）', isin='JP90C000T816', code='9I311269',
                         fee_incl_tax=0.00462, inception='2026-09-25', nisa='成長投資枠のみ（つみたて投資枠は対象外）',
                         index='Solactive・米国超大型テクノロジー株式12指数（配当込み、円換算ベース）',
                         rule='NASDAQ 上場の米国企業（金融を除く）の時価総額上位100からテクノロジー関連の上位12社・年4回・上位7社 各12%・残り5社 各3.2%・大型IPOは臨時に',
                         holdings_2026_09='MSFT 14.96 / NVDA 12.46 / AAPL 12.14 / AMZN 12.04 / SpaceX 11.64 / AVGO 10.81 / GOOGL 10.70 / META 3.32 / MU 3.20 / AMD 3.02（第三者 toushikiso・11〜12位は不明）',
                         sources=['https://www.rakuten-toushin.co.jp/fund/nav/ritech12/pdf/ritech12_P.pdf（交付目論見書 p.2〜3・p.8〜9）',
                                  'https://toushin-lib.fwg.ne.jp/FdsWeb/FDST999900（投資信託協会）', 'https://www.toushikiso.com/news/rakuten-tech-12.html']),
               official_yen_calendar=OFFICIAL_YEN, qqq_yen_calendar_same_method=qy,
               variants={k: dict(rmse=v['rmse'], yen=v['yen']) for k, v in res.items()}, main_variant=best,
               main_variant_note='「テクノロジー関連」の範囲は目論見書に無いので、群の入れ方を変えた版のうち目論見書の暦年の騰落率（円）に最も近い版を主にした（結果を見た当てはめ）。同じ近さなら 2026年9月の実際の上位10社（TSLA が無い）と合う版＝2026-06 の見直しから TSLA を外す版',
               monthly_usd={str(m): v for m, v in sorted(res[best]['rets'].items())},
               monthly_usd_all={k: {str(m): x for m, x in sorted(v['rets'].items())} for k, v in res.items()},
               constituents={str(m): h for m, h in sorted(res[best]['hist'].items())},
               worlds=compute_worlds(), no_price=missing_px, selected_without_price=sel_missing,
               warn=['2010年より前は組み直していない（株数の XBRL が無く、当時の上位〔Sun・JDSU・Yahoo・旧 Broadcom・旧 Dell など〕の価格が Yahoo に無い）',
                     '価格が無い構成銘柄の月は残りの構成銘柄の重みで按分した（0 と読まない）',
                     '株数は提出済みの最新（表紙の株数、無ければ加重平均の基本株数）。見直しは 3・6・9・12月末で選び翌月から（本物は第3金曜あたり）',
                     '配当は源泉税を引く前（配当込みの調整後終値）。費用は引いていない（bestpf_check で信託報酬0.462%を引く）'])
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)


if __name__ == '__main__':
    main()
