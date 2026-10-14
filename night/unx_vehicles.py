#!/usr/bin/env python3
"""night/unx_vehicles.py — 未調査の候補の検定 D・F・G1（読むだけ・門の採点・四関門・席・売却規律・配分・注文書には触れない）

2026-10-14 ユーザー「今までに見つけられなかったものを見つけ出して。調べきれていない組み合わせやETF投資信託など調べられていないものを見つけ出して。」
事前登録 out/unexplored_prereg.json（6f534c92・測る前に固定）の groups.D_vehicle_real_costs・F_smh_vs_sox_fund・G_data_fixes.G1_soxx どおり。

  D  同じ賭けの器の実際に引かれた費用（指数との差）: NASDAQ100（＋円ヘッジの東証 ETF）・SOX・金・円ヘッジの米国20年超国債。
     器は事前登録の一覧＋探索役（scratchpad discovery/*/result.json）が名指しした本に限る（測らなかった本は理由つきで並べる）。
     指数: XNDX・XSOX＝NASDAQ の Global Index Watch（POST /Index/HistoryData・XSOX の 2009-12-21 以前は /docs/AdditionalData_XSOX.csv）／
           金＝GLD の配当込み＋0.40%/年／米国20年超国債＝TLT の配当込み＋0.15%/年（円ヘッジは −（米国1か月 − 日本1か月）の近似）。
     日本の投信・東証 ETF＝投資信託協会の基準価額（分配金を足し戻す・口数の分割と併合は比で戻す）。東証の外国 ETF・純金上場信託
     （協会の一覧に無い）だけは Yahoo の市場価格（分割の検査つき・『市場価格の代わり』と名乗る）。
     日本の器は「指数の前の米国営業日の値 × 前の米国営業日の FRED DEXJPUS」と比べる（bestfund_vehicles.td_fund と同じ合わせ方）。
     実際の費用＝ log(指数の円 ÷ 器) の回帰の傾き（年率・newfunds._slope）と 1年ごとの差の平均（毎日ずらす・bestfund_vehicles と同じ）の両方。
     窓は 1・2・3・5年（記録がある分だけ・終わりは 2026-09-30 以前の最後の日）。
  F  SMH（ドル・1株単位）と SOX の円の投信の取り換えを考える価値があるか（事前登録の2条件）。
  G1 SOXX の配当込みと XSOX（2021-07〜）。条件に当たれば bestfund の SEMI_SOX の確実性等価を XSOX に差し替えて測り直す
     （out/_mw_cache/bf_chains.json と out/bestfund.json を読むだけ・書き換えない・結果はこのファイルの出力にだけ）。

キャッシュ: 環境変数 UNX_D_CACHE（無ければ out/_nx_cache/unx/d/・gitignore 済み）。既存の out/_mw_cache・out/_gaps_cache には書かない
（mw_common・gaps_common の CACHE をこの道具の中だけ差し替える）。投資信託協会への取得は nx_jpfunds_data.Lib（UA に個人の連絡先を載せない）。

  python3 night/unx_vehicles.py        → out/unx_vehicles.json
"""
import bisect, csv, datetime, hashlib, http.cookiejar, io, json, math, os, re, statistics as S, sys, time, unicodedata
import urllib.parse, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
CACHE = os.environ.get('UNX_D_CACHE') or os.path.join(BASE, 'out', '_nx_cache', 'unx', 'd')
os.makedirs(CACHE, exist_ok=True)

import mw_common as M          # noqa: E402
import gaps_common as G        # noqa: E402
M.CACHE = CACHE                # 既存のキャッシュ（out/_mw_cache・out/_gaps_cache）に書かない
G.CACHE = CACHE
import bestfund_data as D      # noqa: E402  費用の表（VEH・外国税の係数 k・配当利回り dy・FX_FEE）
import newfunds as NF          # noqa: E402  _slope（log(器÷指数) の回帰の傾き）
import nx_jpfunds_data as J    # noqa: E402  投資信託協会の Lib（トップを読んでから CSV）

OUT = os.path.join(BASE, 'out', 'unx_vehicles.json')
PREREG = 'out/unexplored_prereg.json（6f534c92）'
END = 20260930                 # 事前登録 common.data_cutoff: 月次は 2026-09 まで
UA = {'User-Agent': 'Mozilla/5.0 (ccf-gate research)'}
SCOUT = '/tmp/claude-0/-home-user-ccf-gate/9d311d2b-9e37-5d72-ab9f-e5499ad3d31c/scratchpad/discovery'
GIW_URL = 'https://indexes.nasdaqomx.com/Index/HistoryData'
XSOX_CSV = 'https://indexes.nasdaqomx.com/docs/AdditionalData_XSOX.csv'
SOX_METH = 'https://indexes.nasdaqomx.com/docs/Methodology_SOX.pdf'
JPX_URL = 'https://www.jpx.co.jp/equities/products/etfs/issues/01.html'
VANECK_SMH = 'https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/overview/'
IDECO_URL = 'https://dc.rakuten-sec.co.jp/service/product/'
UST_URL = ('https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all'
           '?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv')
TIBOR_URL = 'https://www.jbatibor.or.jp/rate/pdf/JAPANESEYEN{y}.pdf'
JITA_SNAP = os.path.join(BASE, 'out', '_nx_cache', 'newfunds', 'jita_full.json')   # newfunds の写真（2026-10-09）・読むだけ
ETFD = os.path.join(BASE, 'out', '_nx_cache', 'newfunds', 'etfd.csv')              # 楽天の海外 ETF 一覧（2026-10-11）・読むだけ
BF_CHAINS = os.path.join(BASE, 'out', '_mw_cache', 'bf_chains.json')              # bestfund のつなぎ（2026-10-11）・読むだけ
BF_OUT = os.path.join(BASE, 'out', 'bestfund.json')
BF_PERSIST = os.path.join(BASE, 'out', 'bestfund_persist.json')
WHOLE = os.path.join(BASE, 'out', 'wholeshare_buy.json')
DEV = []                       # 事前登録から外れた所（理由つき）
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


def ymd(d):
    return datetime.date(d // 10000, d // 100 % 100, d % 100)


def iymd(dt):
    return dt.year * 10000 + dt.month * 100 + dt.day


def before(keys, d):
    """d より前（d を含まない）で最も近いキー"""
    i = bisect.bisect_left(keys, d)
    return keys[i - 1] if i > 0 else None


def r3(x, k=3):
    return None if x is None else round(x, k)


# ═════════════════════════ 取得（キャッシュつき） ═════════════════════════
def fetch(url, name, max_age_days=3, data=None, headers=None, tries=4, cookie=False):
    p = os.path.join(CACHE, name)
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < max_age_days * 86400 and os.path.getsize(p) > 0:
        return open(p, 'rb').read()
    hd = dict(UA)
    hd.update(headers or {})
    err = None
    for i in range(tries):
        try:
            if cookie:
                op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                b = op.open(urllib.request.Request(url, data=data, headers=hd), timeout=120).read()
            else:
                b = urllib.request.urlopen(urllib.request.Request(url, data=data, headers=hd), timeout=120).read()
            open(p + '.tmp', 'wb').write(b)
            os.replace(p + '.tmp', p)
            time.sleep(0.4)
            return b
        except Exception as e:  # noqa
            err = e
            time.sleep(2 ** (i + 1))
    raise RuntimeError(f'取得失敗 {url}: {err}')


# ── 指数（NASDAQ Global Index Watch）
def giw(sym, start):
    body = urllib.parse.urlencode({'id': sym, 'startDate': f'{start}T00:00:00.000', 'endDate': '2026-10-13T00:00:00.000',
                                   'timeOfDay': 'EOD'}).encode()
    b = fetch(GIW_URL, f'giw_{sym}_{start}.json', data=body,
              headers={'X-Requested-With': 'XMLHttpRequest', 'Referer': f'https://indexes.nasdaqomx.com/Index/History/{sym}',
                       'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'})
    j = json.loads(b)
    out = {}
    for r in j['aaData']:
        ms = int(r['TimeStamp'].strip('/').replace('Date(', '').replace(')', ''))
        d = datetime.datetime.utcfromtimestamp(ms / 1000).date()
        if r.get('Value'):
            out[iymd(d)] = float(r['Value'])
    return out


def xsox_levels():
    """XSOX（PHLX SOX の配当込み）の日次の水準: 2001-06-29〜2009-12-21 は AdditionalData_XSOX.csv、2009-12-22〜 は GIW"""
    old = {}
    t = fetch(XSOX_CSV, 'AdditionalData_XSOX.csv', max_age_days=30).decode('latin-1')
    for row in csv.reader(io.StringIO(t)):
        if len(row) >= 2 and re.match(r'^\d+/\d+/\d{4}$', row[0].strip()):
            try:
                mo, dd, yy = (int(x) for x in row[0].strip().split('/'))
                old[yy * 10000 + mo * 100 + dd] = float(row[1])
            except ValueError:
                pass
    new = giw('XSOX', '2009-12-01')
    first_new = min(new)
    out = {k: v for k, v in old.items() if k < first_new}
    out.update(new)
    ks = sorted(out)
    i = ks.index(first_new)
    jump = out[ks[i]] / out[ks[i - 1]] - 1
    return out, {'csv_rows': len(old), 'csv_last': max(old), 'giw_first': first_new, 'giw_last': max(new),
                 'splice_day_return_pct': round(100 * jump, 3), 'overlap_days': len(set(old) & set(new))}


# ── Yahoo（mw_common.yahoo の日次・キャッシュはこの道具の場所）
def yahoo_levels(t, er=0.0):
    r = M.yahoo(t, interval='1d')
    lv, x = {}, 1.0
    for k in sorted(r):
        x *= 1 + r[k] + er / 252
        lv[k] = x
    return lv


def yahoo_tse_price(t):
    """東証の市場価格（終値）。分割・併合を比で戻す（Yahoo は東証の分割を落とすことがある）。分配金は入らない（1540・1326 は分配しない）"""
    M.yahoo(t, interval='1d')
    nm = f'yh_{t.replace("^", "IDX_").replace("=", "_")}_1d.json'
    j = json.load(open(os.path.join(CACHE, nm)))['chart']['result'][0]
    off = j.get('meta', {}).get('gmtoffset') or 0
    q = j['indicators']['quote'][0]['close']
    px = {}
    for ts, c in zip(j['timestamp'], q):
        if c:
            px[iymd(datetime.datetime.utcfromtimestamp(ts + off))] = c
    ks = sorted(px)
    nice = (2, 3, 4, 5, 8, 10, 16, 20, 25, 50, 100, 200, 500, 1000)
    f, ev, lv = 1.0, [], {}
    fac = {ks[-1]: 1.0}
    for i in range(len(ks) - 1, 0, -1):
        q_ = px[ks[i]] / px[ks[i - 1]]
        if q_ < 0.55 or q_ > 1.8:
            k_ = min(nice, key=lambda z: abs(math.log(z * q_)) if q_ < 1 else abs(math.log(q_ / z)))
            if (q_ < 1 and abs(k_ * q_ - 1) < 0.08) or (q_ > 1 and abs(q_ / k_ - 1) < 0.08):
                f = f / k_ if q_ < 1 else f * k_
                ev.append((ks[i], ('1:%d' % k_) if q_ < 1 else ('%d:1' % k_)))
            else:
                ev.append((ks[i], f'説明できない1日の動き {q_:.3f}'))
        fac[ks[i - 1]] = f
    for k in ks:
        lv[k] = px[k] * fac[k]
    return lv, ev


# ── 投資信託協会の基準価額（分配金を足し戻す・口数の分割と併合を戻す）
_LIB = {}


def jita_rows(isin, assoc):
    p = os.path.join(CACHE, f'jita_{assoc}.csv')
    if not (os.path.exists(p) and time.time() - os.path.getmtime(p) < 3 * 86400 and os.path.getsize(p) > 0):
        if 'lib' not in _LIB:
            _LIB['lib'] = J.Lib()
        b = _LIB['lib'].csv(isin, assoc)
        if b is None:
            return None, []
        open(p + '.tmp', 'wb').write(b)
        os.replace(p + '.tmp', p)
        time.sleep(0.6)
    t = open(p, 'rb').read().decode('cp932', errors='replace').splitlines()
    rows = []
    for line in t[1:]:
        x = line.split(',')
        m = re.match(r'(\d{4})年(\d{2})月(\d{2})日', x[0].strip())
        if not m:
            continue
        try:
            nav = float(x[1])
        except ValueError:
            continue
        dv = 0.0
        if len(x) > 3 and x[3].strip():
            try:
                dv = float(x[3])
            except ValueError:
                dv = 0.0
        rows.append((int(m.group(1) + m.group(2) + m.group(3)), nav, dv))
    rows.sort()
    nice = (2, 3, 4, 5, 8, 10, 16, 20, 25, 50, 100, 200, 500, 1000)
    adj, out, ev = 1.0, [], []
    for i, (d, nav, dv) in enumerate(rows):
        if i:
            q = rows[i - 1][1] / nav            # 前日 ÷ 今日
            if q > 1.8 or q < 0.55:
                hit = False
                for k in nice:
                    if abs(q / k - 1) < 0.05:    # 今日が前日の約 1/k＝1口→k口の分割
                        adj *= k; ev.append((d, f'1:{k}')); hit = True; break
                    if abs(q * k - 1) < 0.05:    # 今日が前日の約 k 倍＝k口→1口の併合
                        adj /= k; ev.append((d, f'{k}:1')); hit = True; break
                if not hit:
                    ev.append((d, f'説明できない1日の動き {1 / q:.3f}'))
        out.append((d, nav * adj, dv * adj))
    lv, x = {out[0][0]: 1.0}, 1.0
    for (a, n0, _), (b, n1, v1) in zip(out, out[1:]):
        x *= (n1 + v1) / n0
        lv[b] = x
    return lv, ev


# ── 為替・金利
def fred_daily(sid):
    raw = G._cached(f'fred_{sid}.csv', f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}', days=3).decode()
    out = {}
    for row in list(csv.reader(io.StringIO(raw)))[1:]:
        if len(row) >= 2 and row[1] not in ('.', ''):
            try:
                out[int(row[0].replace('-', ''))] = float(row[1])
            except ValueError:
                pass
    return out


def fx_daily():
    """FRED DEXJPUS（日次・円/ドル）。FRED の CSV が取れないときだけ、今日取った同じ系列の写しを使う（どれを使ったかを出力に書く）"""
    try:
        fx = fred_daily('DEXJPUS')
        return fx, 'FRED DEXJPUS https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXJPUS（この実行で取得）'
    except Exception as e:  # noqa
        cands = [os.path.join(BASE, 'out', '_gaps_cache', 'fred_DEXJPUS.csv'), os.path.join(SCOUT, 'tse-us-index', 'data', 'fred_DEXJPUS_new.csv')]
        best = None
        for p in cands:
            if os.path.exists(p):
                rows = [r for r in csv.reader(open(p)) if len(r) >= 2 and r[1] not in ('.', '')][1:]
                if rows and (best is None or rows[-1][0] > best[1]):
                    best = (p, rows[-1][0], rows)
        if not best:
            raise
        DEV.append(f'FRED DEXJPUS の取得が失敗（{e}）＝同じ系列の写し {best[0]}（最後 {best[1]}）を使った')
        return {int(r[0].replace('-', '')): float(r[1]) for r in best[2]}, f'FRED DEXJPUS の写し {best[0]}'


def us1m_daily():
    """米国1か月（Treasury の1か月の利回り・%）。FRED DGS1MO、取れなければ財務省の日次 CSV（FRED の出所）"""
    try:
        return fred_daily('DGS1MO'), 'FRED DGS1MO https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS1MO'
    except Exception as e:  # noqa
        out = {}
        for y in range(2019, 2027):
            t = fetch(UST_URL.format(y=y), f'ust_curve_{y}.csv', max_age_days=3 if y >= 2026 else 365).decode('utf-8', 'replace')
            rd = list(csv.reader(io.StringIO(t)))
            h = rd[0]
            c = h.index('1 Mo')
            for r in rd[1:]:
                if len(r) > c and r[c]:
                    mo, dd, yy = (int(x) for x in r[0].split('/'))
                    out[yy * 10000 + mo * 100 + dd] = float(r[c])
        DEV.append(f'FRED DGS1MO の取得が失敗（{e}）＝財務省の日次 CSV（1 Mo）を使った')
        return out, '米国財務省 daily treasury par yield curve（1 Mo）'


def jp1m_daily():
    """日本1か月＝全銀協 日本円 TIBOR 1か月（年ごとの PDF・2019〜2026）。※値は計算にだけ使い、出力に系列を写さない（再配信は要問い合わせ）"""
    import pypdf
    out, used = {}, []
    for y in range(2019, 2027):
        p = os.path.join(CACHE, f'tibor_{y}.pdf')
        fetch(TIBOR_URL.format(y=y), f'tibor_{y}.pdf', max_age_days=3 if y >= 2026 else 365)
        r = pypdf.PdfReader(p)
        n = 0
        for pg in r.pages:
            for line in (pg.extract_text() or '').splitlines():
                m = re.match(r'^(\d{4})/(\d{2})/(\d{2})\s+(.*)$', line.strip())
                if not m:
                    continue
                nums = re.findall(r'-?\d+\.\d+', m.group(4))
                if len(nums) == 5:           # 2017年以降の5つの期間（1週・1か月・3か月・6か月・12か月）
                    out[int(m.group(1) + m.group(2) + m.group(3))] = float(nums[1]); n += 1
                elif len(nums) == 13:        # 13の期間（1週・1〜12か月）
                    out[int(m.group(1) + m.group(2) + m.group(3))] = float(nums[1]); n += 1
        used.append((y, n))
    return out, used


def hedged_levels(base_lv, us, jp):
    """ドル建ての配当込みの水準 → 円ヘッジの近似: 毎日（前の米国営業日→今日）−（米国1か月 − 日本1か月）×日数/365（前の日の金利）"""
    uk, jk = sorted(us), sorted(jp)
    ks = sorted(base_lv)
    out, x = {ks[0]: 1.0}, 1.0
    miss = 0
    for a, b in zip(ks, ks[1:]):
        ua, ja = before(uk, a + 1), before(jk, a + 1)
        if ua is None or ja is None:
            out = {b: 1.0}; x = 1.0; miss += 1
            continue
        days = (ymd(b) - ymd(a)).days
        x *= base_lv[b] / base_lv[a] * math.exp(-(us[ua] - jp[ja]) / 100 * days / 365)
        out[b] = x
    return out


# ── 表の費用・NISA の枠・楽天の取扱
def jita_snapshot():
    d = json.load(open(JITA_SNAP))
    return {r['associFundCd']: r for r in d['rows']}, d.get('std')


def jpx_table():
    t = fetch(JPX_URL, 'jpx_etf_01.html', max_age_days=7).decode('utf-8', 'replace')

    def clean(s):
        return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s)).strip()
    out = {}
    for r in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S):
        c = [clean(x) for x in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S)]
        if len(c) >= 6 and re.match(r'^[0-9A-Z]{4}$', c[1]):
            out[c[1]] = {'index': c[0], 'name': c[2], 'issuer': c[3], 'fee': c[4], 'nisa': c[5]}
    return out


def pct_of(s):
    m = re.search(r'(\d+\.\d+|\d+)\s*[%％]', s or '')
    return float(m.group(1)) if m else None


def etfd_er():
    t = open(ETFD, 'rb').read().decode('utf-8-sig', 'replace')
    out = {}
    for r in csv.reader(io.StringIO(t)):
        if len(r) > 5:
            try:
                out[r[1]] = float(r[5])
            except ValueError:
                pass
    return out


def vaneck_smh_er():
    try:
        t = fetch(VANECK_SMH, 'vaneck_smh.html', max_age_days=7, cookie=True).decode('utf-8', 'replace')
        txt = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', t))
        m = re.search(r'Expense Ratio\s*((?:\S+\s+){0,12}?)(\d+\.\d+)%', txt)
        if m:
            return float(m.group(2)), f'VanEck の SMH のページ {VANECK_SMH}（「Expense Ratio」の数字）'
    except Exception as e:  # noqa
        DEV.append(f'VanEck の SMH のページが取れなかった（{e}）＝楽天の海外 ETF 一覧の経費率を使った')
    return None, None


def ideco_lineup():
    try:
        t = fetch(IDECO_URL, 'rakuten_ideco_product.html', max_age_days=7).decode('utf-8', 'replace')
        t2 = unicodedata.normalize('NFKC', re.sub(r'<[^>]+>', ' ', t))
        res = {}
        for k, pat in (('NASDAQ100', r'NASDAQ-?100[^\s]{0,20}'), ('SOX・半導体', r'(SOX|半導体)[^\s]{0,20}'), ('金', r'ゴールド[^\s]{0,30}')):
            res[k] = sorted(set(x if isinstance(x, str) else x[0] for x in re.findall(pat, t2)))
        names = sorted(set(re.findall(r'(楽天・プラス・NASDAQ-100インデックス・ファンド|ステート・ストリート・ゴールド・オープン\(為替ヘッジなし\)|'
                                      r'ステートストリート・ゴールドファンド\(為替ヘッジあり\))', t2)))
        return {'url': IDECO_URL, 'found_fund_names': names, 'keyword_hits': res}
    except Exception as e:  # noqa
        return {'url': IDECO_URL, 'error': str(e)}


# ═════════════════════════ 実際の費用 ═════════════════════════
def align_jp(lv_v, lv_i, fx=None):
    """器の日 d ↔ 指数の d より前の最後の日（× d より前の最後のドル円）。7日より古い指数・為替は使わない"""
    ik = sorted(lv_i)
    fk = sorted(fx) if fx else None
    out = {}
    for d in sorted(lv_v):
        k = before(ik, d)
        if k is None or (ymd(d) - ymd(k)).days > 7:
            continue
        if fx:
            f = before(fk, d)
            if f is None or (ymd(d) - ymd(f)).days > 7:
                continue
            out[d] = lv_i[k] * fx[f]
        else:
            out[d] = lv_i[k]
    return out


def align_us(lv_v, lv_i):
    return {d: lv_i[d] for d in lv_v if d in lv_i}


def window_costs(lv_v, lv_i):
    """→ {窓: {...}}。slope＝−傾き（log(器÷指数)）、roll＝−(exp(1年ごとの差の平均)−1)。％/年。正＝器が指数に負けた＝費用"""
    ds = sorted(d for d in set(lv_v) & set(lv_i) if d <= END)
    if len(ds) < 30:
        return {}, None, None
    E = ds[-1]
    res = {}
    for y in (1, 2, 3, 5):
        st = iymd(datetime.date(ymd(E).year - y, ymd(E).month, min(ymd(E).day, 28)))
        i0 = bisect.bisect_left(ds, st)
        if i0 >= len(ds) or (ymd(ds[i0]) - ymd(st)).days > 7:
            continue
        s0 = ds[i0]
        w = ds[i0:]
        sl = NF._slope(lv_v, lv_i, s0, E)
        if y == 1:
            span = (ymd(E) - ymd(s0)).days / 365.25
            m = (math.log(lv_v[E] / lv_v[s0]) - math.log(lv_i[E] / lv_i[s0])) / span
            n = 1
        else:
            diffs = []
            for k, t in enumerate(w):
                if t < iymd(datetime.date(ymd(s0).year + 1, ymd(s0).month, min(ymd(s0).day, 28))):
                    continue
                j = bisect.bisect_left(w, iymd(datetime.date(ymd(t).year - 1, ymd(t).month, min(ymd(t).day, 28))))
                if j >= k:
                    continue
                s_ = w[j]
                span = (ymd(t) - ymd(s_)).days / 365.25
                if span < 0.95:
                    continue
                diffs.append((math.log(lv_v[t] / lv_v[s_]) - math.log(lv_i[t] / lv_i[s_])) / span)
            if len(diffs) < 100:
                continue
            m = sum(diffs) / len(diffs)
            n = len(diffs)
        res[f'{y}y'] = {'from': s0, 'to': E, 'slope': r3(-sl[0]) if sl else None, 'roll': r3(-100 * (math.exp(m) - 1)), 'n_1y_diffs': n}
    full = None
    if len(ds) > 80:
        sl = NF._slope(lv_v, lv_i, ds[20], E)
        full = {'from': ds[20], 'to': E, 'slope': r3(-sl[0]) if sl else None, 'years': round((ymd(E) - ymd(ds[0])).days / 365.25, 2)}
    return res, full, (ds[0], E)


# ═════════════════════════ 器の一覧（事前登録＋探索役） ═════════════════════════
# (賭け, 名前, 種類, 鍵, 出所)。種類: jita＝日本の投信 / jita_etf＝東証 ETF（協会の基準価額）/ us＝米国 ETF / tse_px＝東証の市場価格（協会に無い）
VEH = [
    ('NDX', 'iFreeNEXT NASDAQ100インデックス', 'jita', ('JP90C000GUN2', '04317188'), '事前登録'),
    ('NDX', 'インデックスファンドNASDAQ100（アメリカ株式）〔アモーヴァ〕', 'jita', ('JP90C000KNQ2', '02314208'), '探索役 kodomo-ndx-vehicles'),
    ('NDX', 'eMAXIS NASDAQ100インデックス', 'jita', ('JP90C000L9D2', '0331A211'), '事前登録'),
    ('NDX', 'ニッセイNASDAQ100インデックスファンド', 'jita', ('JP90C000PDY6', '29313233'), '事前登録'),
    ('NDX', '楽天・プラス・NASDAQ-100インデックス・ファンド', 'jita', ('JP90C000QF22', '9I314241'), '事前登録（iDeCo の器）'),
    ('NDX', 'たわらノーロードNASDAQ100', 'jita', ('JP90C000Q7S9', '4731523C'), '探索役 kodomo-ndx-vehicles・wf-jp-funds-index'),
    ('NDX', 'NZAM・ベータNASDAQ100', 'jita', ('JP90C000JYE7', '25316203'), '探索役 kodomo-ndx-vehicles'),
    ('NDX', 'SBI・インベスコQQQ・NASDAQ100インデックス・ファンド', 'jita', ('JP90C000PVT8', '89311238'), '探索役 kodomo-ndx-vehicles・tse-us-index'),
    ('NDX', 'SBI NASDAQ100インデックス・ファンド', 'jita', ('JP90C000SWF9', '89311265'), '探索役 kodomo-ndx-vehicles'),
    ('NDX', 'Smart-i NASDAQ100インデックス', 'jita', ('JP90C000T6E8', 'AJ312269'), '探索役 kodomo-ndx-vehicles'),
    ('NDX', '東証 2840 iFreeETF NASDAQ100（為替ヘッジなし）', 'jita_etf', ('JP3049460003', '04314221', '2840'), '事前登録'),
    ('NDX', '東証 1545 NEXT FUNDS NASDAQ-100（為替ヘッジなし）', 'jita_etf', ('JP3047240001', '01313108', '1545'), '事前登録'),
    ('NDX', '東証 2631 MAXISナスダック100上場投信', 'jita_etf', ('JP3049190006', '03314212', '2631'), '探索役 tse-us-index'),
    ('NDX', '東証 2568 上場インデックスファンド米国株式（NASDAQ100）為替ヘッジなし', 'jita_etf', ('JP3049090008', '02313209', '2568'), '探索役 tse-us-index・wf-jp-funds-index'),
    ('NDX', '東証 534A NZAM 上場投信 NASDAQ100（為替ヘッジなし）', 'jita_etf', ('JP3051350001', '25313263', '534A'), '探索役 tse-us-index'),
    ('NDX', 'QQQM', 'us', 'QQQM', '事前登録'),
    ('NDX_H', '東証 2841 iFreeETF NASDAQ100（為替ヘッジあり）', 'jita_etf', ('JP3049470002', '04313221', '2841'), '事前登録'),
    ('NDX_H', '東証 2632 MAXISナスダック100上場投信（為替ヘッジあり）', 'jita_etf', ('JP3049200003', '03315212', '2632'), '探索役 tse-us-index（名前だけ・測らなかった本）'),
    ('NDX_H', '東証 2569 上場インデックスファンド米国株式（NASDAQ100）為替ヘッジあり', 'jita_etf', ('JP3049100005', '02314209', '2569'), '探索役 tse-us-index（同上）'),
    ('NDX_H', '東証 2087 NZAM 上場投信 NASDAQ100（為替ヘッジあり）', 'jita_etf', ('JP3050050008', '25315239', '2087'), '探索役 tse-us-index（同上・NZAM hedged）'),
    ('SOX', '楽天・プラス・SOXインデックス・ファンド', 'jita', ('JP90C000QF30', '9I315241'), '事前登録'),
    ('SOX', 'ニッセイSOX指数インデックスファンド（米国半導体株）', 'jita', ('JP90C000PDZ3', '29314233'), '事前登録'),
    ('SOX', 'インデックスファンドSOX指数（米国上場半導体株式）〔アモーヴァ〕', 'jita', ('JP90C000Q1Q6', '02313239'), '探索役 tse-us-index'),
    ('SOX', 'ニッセイ・インデックス・SOX（米国半導体株）', 'jita', ('JP90C000R8K3', '2931224A'), '探索役 tse-us-index'),
    ('SOX', '東証 2243 グローバルX 半導体 ETF', 'jita_etf', ('JP3049860004', 'B5311234', '2243'), '事前登録'),
    ('SOX', 'SMH（指数は MVIS US Listed Semiconductor 25＝SOX ではない）', 'us', 'SMH', '事前登録'),
    ('SOX', 'SOXX（2021-06-21 から SOX ではない）', 'us', 'SOXX', '事前登録（別に名指し）'),
    ('GOLD', 'ステート・ストリート・ゴールド・オープン（為替ヘッジなし）', 'jita', ('JP90C000RXU8', '55311258'), '事前登録・探索役 ideco-lineup'),
    ('GOLD', 'iシェアーズ ゴールドインデックス・ファンド（為替ヘッジなし）', 'jita', ('JP90C0009G00', '4831M139'), '探索役 wf-jp-funds-index'),
    ('GOLD', '東証 314A iシェアーズ ゴールド ETF', 'jita_etf', ('JP3050630007', '48312251', '314A'), '事前登録・探索役 tse-other'),
    ('GOLD', '東証 1328 NEXT FUNDS 金価格連動型上場投信', 'jita_etf', ('JP3046490003', '01311078', '1328'), '探索役 wf-jp-funds-index・tse-other'),
    ('GOLD', '東証 447A ステート・ストリート・スパイダー ゴールド ETF（為替ヘッジなし）', 'jita_etf', ('JP3050970007', '5531125B', '447A'), '探索役 tse-other'),
    ('GOLD', '東証 425A グローバルX ゴールド ETF', 'jita_etf', ('JP3050930001', 'B5312259', '425A'), '探索役 tse-other'),
    ('GOLD', '東証 1540 純金上場信託（現物国内保管型）', 'tse_px', '1540.T', '事前登録・探索役 tse-other'),
    ('GOLD', '東証 1326 SPDR ゴールド・シェア', 'tse_px', '1326.T', '事前登録・探索役 tse-other'),
    ('GOLD', 'GLDM', 'us', 'GLDM', '事前登録'),
    ('UST20H', '東証 2621 iシェアーズ 米国債20年超 ETF（為替ヘッジあり）', 'jita_etf', ('JP3049130002', '4831220A', '2621'), '事前登録'),
    ('UST20H', '東証 183A MAXIS米国国債20年超上場投信（為替ヘッジあり）', 'jita_etf', ('JP3050400005', '03313244', '183A'), '探索役 tse-other'),
    ('UST20H', '東証 179A グローバルX 超長期米国債 ETF（為替ヘッジあり・ICE 25年超）', 'jita_etf', ('JP3050360001', 'B5312244', '179A'), '探索役 tse-other'),
]
NOT_MEASURED = [
    ('NDX', 'Tracers NASDAQ100（プレーン）', '存在しない（投資信託協会の一覧 2026-10-09 にあるのは「毎月決算・予想分配金提示型」〔JP90C000TCP8・2026-09-24 設定・NISA 対象外＝nisaGrowthFlg 9〕と「NASDAQ100ゴールドプラス」〔JP90C000RH60・NASDAQ100＋金の先物の重ね＝別の賭け・NISA 対象外〕だけ）'),
    ('NDX', '東証 587A インベスコQQQトラスト（QQQ の東証上場）', '外国 ETF で協会の基準価額が無い・東証の記録は 2026-06-09〜＝1年未満（市場価格でも1年の窓が取れない）'),
    ('NDX', '東証 392A iシェアーズ NASDAQ トップ30', '指数が違う（NASDAQ100 トップ30）'),
    ('NDX', '東証 2244 グローバルX US テック・トップ20・316A iFreeETF FANG+', '指数が違う（別の賭け）'),
    ('SOX', 'iFreeNEXT SOX', '存在しない（投資信託協会の一覧 2026-10-09 に無い）'),
    ('SOX', '東証 2644 グローバルX 半導体関連-日本株式', '指数が SOX ではない（FactSet Japan Semiconductor）'),
    ('SOX', '東証 200A NEXT FUNDS 日経半導体株', '指数が SOX ではない（日経半導体株指数）'),
    ('SOX', '東証 346A NEXT FUNDS S&P500 半導体35%キャップ・iFreeNEXT 全世界半導体・東証 639A メモリ', '指数が SOX ではない'),
    ('GOLD', '他の円の金の投信（たわらノーロードゴールド・楽天・ゴールド・ファンド・SMTゴールド・Smart-i ゴールド・ニッセイゴールド ほか）', '事前登録の一覧にも探索役の一覧にも無い＝測らない（事前登録「器のリストは測る前のこの一覧＋探索役の一覧に限る」）'),
    ('UST20H', '東証 238A iシェアーズ 米国債25年超ロングデュレーション（ヘッジあり）', '指数が STRIPS の元本25年超＝TLT（20年超の利付債）より残存がずっと長い'),
    ('UST20H', '東証 1482・2839・2016・2090・1487（7〜10年・ヘッジあり）・382A（3〜5年・ヘッジあり）', '残存が違う（20年超ではない）＝TLT の代わりの指数と比べられない'),
]
INDEX_NAME = {'NDX': 'XNDX（NASDAQ-100 トータルリターン・ドル）× DEXJPUS', 'NDX_H': 'XNDX の円ヘッジの近似（−（米国1か月 − 日本1か月））',
              'SOX': 'XSOX（PHLX SOX トータルリターン・ドル）× DEXJPUS', 'GOLD': 'GLD の配当込み＋0.40%/年（ドル）× DEXJPUS',
              'UST20H': 'TLT の配当込み＋0.15%/年 の円ヘッジの近似（−（米国1か月 − 日本1か月））'}
# 今使っている器・予定の器（事前登録 D の判定の比べる相手）
CURRENT = {'NDX': [('つみたて投資枠（今・こどもNISA も予定）', 'iFreeNEXT NASDAQ100インデックス', 'tsumitate'),
                   ('成長投資枠（つみたて枠を超えた分）', 'QQQM', 'growth'),
                   ('iDeCo', '楽天・プラス・NASDAQ-100インデックス・ファンド', 'ideco')],
           'SOX': [('成長投資枠（今の半導体の器・ドル・1株単位）', 'SMH（指数は MVIS US Listed Semiconductor 25＝SOX ではない）', 'growth')],
           'GOLD': [('成長投資枠（今は持っていない・bestfund の器の表 VEH の GOLD の器）', 'GLDM', 'growth')]}


# ═════════════════════════ 本体 ═════════════════════════
def main():
    t0 = time.time()
    snap, snap_std = jita_snapshot()
    jpx = jpx_table()
    er_rk = etfd_er()
    smh_issuer, smh_src = vaneck_smh_er()
    fx, fx_src = fx_daily()
    us, us_src = us1m_daily()
    jp, jp_used = jp1m_daily()
    log('fx', fx_src, max(fx), 'us1m', max(us), 'jp1m', max(jp), jp_used)

    # 指数
    xndx = giw('XNDX', '2015-01-01')
    xsox, splice = xsox_levels()
    gld = yahoo_levels('GLD', 0.0040)
    tlt = yahoo_levels('TLT', 0.0015)
    idx_usd = {'NDX': xndx, 'SOX': xsox, 'GOLD': gld}
    idx_hedged = {'NDX_H': hedged_levels(xndx, us, jp), 'UST20H': hedged_levels(tlt, us, jp)}
    log('XNDX', min(xndx), max(xndx), 'XSOX', min(xsox), max(xsox), splice)

    ideco = ideco_lineup()
    rows = []
    for bet, nm, kind, key, src in VEH:
        e = {'bet': bet, 'vehicle': nm, 'kind': kind, 'source': src}
        ev = []
        if kind in ('jita', 'jita_etf'):
            isin, assoc = key[0], key[1]
            e.update(isin=isin, assoc=assoc)
            s = snap.get(assoc)
            if s:
                e['jita_name'] = unicodedata.normalize('NFKC', s.get('fundNm') or '')
                e['established'] = (s.get('establishedDate') or '')[:10]
                e['tsumitate'] = s.get('nisaFlg') == '1'
                e['growth_jita'] = s.get('nisaGrowthFlg') == '1'
                rk = [i for i in (s.get('institutionInfo') or []) if i.get('instName') == '楽天証券']
                e['rakuten'] = ({'sold': True, 'sales_fee_pct': float(rk[0].get('salesFee') or 0)} if rk else {'sold': False}) if kind == 'jita' else {'sold': True, 'note': '東証 ETF＝国内株として楽天で売買できる'}
                e['fee_jita_ex_tax'] = float(s['trustReward']) if s.get('trustReward') not in (None, '') else None
            if kind == 'jita_etf':
                code = key[2]
                e['code'] = code
                j = jpx.get(code)
                if j:
                    e['jpx'] = j
                    f = pct_of(j['fee'])
                    taxed = '税込' in j['fee']
                    e['stated_fee_incl_tax'] = r3(f if taxed else f * 1.1, 4) if f is not None else None
                    e['stated_fee_src'] = f"JPX の ETF 一覧 {JPX_URL}（{j['fee']}・{'税込のまま' if taxed else '税抜×1.1'}）"
                    e['growth'] = j['nisa'].startswith('●')
                else:
                    e['growth'] = e.get('growth_jita')
                    if e.get('fee_jita_ex_tax') is not None:
                        e['stated_fee_incl_tax'] = r3(e['fee_jita_ex_tax'] * 1.1, 4)
                        e['stated_fee_src'] = '投資信託協会の一覧（税抜×1.1）・JPX の一覧に無かった'
                if e.get('growth_jita') is not None and e.get('growth') != e.get('growth_jita'):
                    e['nisa_flag_conflict'] = f"JPX の NISA の印 {'●' if e.get('growth') else '無し'} と投資信託協会の nisaGrowthFlg {'1' if e.get('growth_jita') else '1以外'} が食い違う"
            else:
                e['growth'] = e.get('growth_jita')
                if e.get('fee_jita_ex_tax') is not None:
                    e['stated_fee_incl_tax'] = r3(e['fee_jita_ex_tax'] * 1.1, 4)
                    e['stated_fee_src'] = '投資信託協会の一覧 2026-10-09（trustReward 税抜×1.1）'
                if assoc == '89311238':   # SBI・インベスコQQQ＝中で QQQ を買う（QQQ の経費は信託報酬に入らない）
                    e['stated_fee_incl_tax'] = r3(e['fee_jita_ex_tax'] * 1.1 + 0.18, 4)
                    e['stated_fee_src'] = '投資信託協会の信託報酬（税抜×1.1）＋中の QQQ の経費 0.18%（JPX の 587A＝QQQ と同じ値）'
            lv, ev = jita_rows(isin, assoc)
            if lv is None:
                e['error'] = '投資信託協会の CSV が取れなかった（償還済み・存在しない）'
                rows.append(e)
                continue
            base = idx_hedged[bet] if bet in idx_hedged else idx_usd[bet]
            li = align_jp(lv, base, None if bet in idx_hedged else fx)
            e['data'] = '投資信託協会の基準価額＋分配金（東証 ETF も基準価額）'
        elif kind == 'us':
            e['ticker'] = key
            e['growth'] = key in er_rk
            e['rakuten'] = {'sold': key in er_rk, 'note': '楽天の海外 ETF 一覧（2026-10-11）にあるか'}
            e['stated_fee_incl_tax'] = er_rk.get(key)
            e['stated_fee_src'] = '楽天の海外 ETF 一覧の経費率（2026-10-11）'
            if key == 'SMH' and smh_issuer is not None:
                e['stated_fee_incl_tax'] = smh_issuer
                e['stated_fee_src'] = smh_src
            if key == 'SOXX' and key not in er_rk:
                e['stated_fee_incl_tax'] = 0.34
                e['stated_fee_src'] = 'iShares の公表値 0.34%（楽天の一覧に無い＝楽天では買えない）'
            lv = yahoo_levels(key)
            li = align_us(lv, idx_usd[bet])
            e['data'] = 'Yahoo の調整後終値（配当は源泉なしで再投資）。指数と同じ米国の終値どうし＝円にしても同じドル円が両方に掛かり消える'
        else:   # tse_px
            e['ticker'] = key
            code = key.split('.')[0]
            j = jpx.get(code)
            if j:
                e['jpx'] = j
                f = pct_of(j['fee'])
                foreign = '注2' in j['name'] or code == '1326'
                e['stated_fee_incl_tax'] = r3(f if (foreign or '税込' in j['fee']) else f * 1.1, 4) if f is not None else None
                e['stated_fee_src'] = f"JPX の ETF 一覧（{j['fee']}・{'外国 ETF の管理費用＝消費税なし' if foreign else '税抜×1.1'}）"
                e['growth'] = j['nisa'].startswith('●')
            e['rakuten'] = {'sold': True, 'note': '東証上場＝国内株として楽天で売買できる'}
            lv, ev = yahoo_tse_price(key)
            li = align_jp(lv, idx_usd[bet], fx)
            e['data'] = '⚠ Yahoo の市場価格（代わり）: 投資信託協会に基準価額が無い。分割は比で戻した・分配金はない本（1540・1326）。基準価額でないので市場の上乗せ・割引と東京の時刻のずれが混ざる'
        if ev:
            e['unit_events'] = [f'{d} {x}' for d, x in ev[-6:]]
        w, full, span = window_costs(lv, li)
        e['windows'] = w
        e['full_record_slope'] = full
        e['record'] = f'{span[0]}〜{span[1]}' if span else None
        # NISA の中で手元に残る差（日本の器は基準価額に外国税が入っている・米国 ETF は取り戻せない外国税と両替を足す）
        add = 0.0
        if kind == 'us':
            vv = D.VEH['NDX' if bet == 'NDX' else ('SEMI_MV' if key == 'SMH' else ('SEMI_SOX' if key == 'SOXX' else 'GOLD'))]
            add = 100 * (vv['k'] * vv['dy'] + D.FX_FEE)
            e['nisa_add_pct'] = r3(add)
            e['nisa_add_note'] = f"取り戻せない配当の外国税 {vv['k']:.2f}×配当利回り {100 * vv['dy']:.2f}%＋両替 {100 * D.FX_FEE:.2f}%（bestfund_data.VEH・FX_FEE）"
        prim = '3y' if '3y' in w else ('2y' if '2y' in w else None)
        e['primary_window'] = prim
        if prim:
            e['real_cost'] = w[prim]['roll']
            e['real_cost_slope'] = w[prim]['slope']
            e['nisa_cost'] = r3(w[prim]['roll'] + add)
            if e.get('stated_fee_incl_tax') is not None:
                e['hidden_vs_stated'] = r3(w[prim]['roll'] - e['stated_fee_incl_tax'])
                e['hidden_vs_stated_slope'] = r3(w[prim]['slope'] - e['stated_fee_incl_tax']) if w[prim]['slope'] is not None else None
        else:
            e['real_cost'] = None
            e['note_short'] = '記録が2年未満＝並びに入れない（1年の窓・設定来の傾きは参考）'
        rows.append(e)
        log(f"{bet:6} {nm[:38]:38} {e.get('record')} 表{e.get('stated_fee_incl_tax')} " +
            ' '.join(f"{k}:{v['roll']}/{v['slope']}" for k, v in w.items()) + f" 主{prim} NISA{e.get('nisa_cost')}")

    # ── D の判定
    by = {}
    for e in rows:
        by.setdefault(e['bet'], []).append(e)
    D_out = {}
    for bet, lst in by.items():
        ranked = sorted([x for x in lst if x.get('nisa_cost') is not None], key=lambda x: x['nisa_cost'])
        ranking = [{'rank': i + 1, 'vehicle': x['vehicle'], 'window': x['primary_window'], 'nisa_cost': x['nisa_cost'],
                    'real_cost_roll': x['real_cost'], 'real_cost_slope': x['real_cost_slope'], 'stated_fee': x.get('stated_fee_incl_tax'),
                    'tsumitate': x.get('tsumitate'), 'growth': x.get('growth'), 'rakuten': x.get('rakuten')} for i, x in enumerate(ranked)]
        named, cmp_rows = [], []
        for label, cur_nm, frame in CURRENT.get(bet, []):
            cur = next((x for x in lst if x['vehicle'] == cur_nm), None)
            if cur is None:
                continue
            cur_cost_by = {}
            if bet == 'SOX' and cur_nm.startswith('SMH'):
                base = r3((cur.get('stated_fee_incl_tax') or 0.35) + cur.get('nisa_add_pct', 0))
                cur_basis = f"SMH の自分の指数（MVIS US Listed Semiconductor 25）の日次は無料で取れない（marketvector.com は 403）＝表の経費率 {cur.get('stated_fee_incl_tax')}%＋{cur.get('nisa_add_pct')}% を使う"
                cur_cost_by = {'3y': base, '2y': base}
            else:
                for wn in ('3y', '2y'):
                    if wn in cur['windows']:
                        cur_cost_by[wn] = r3(cur['windows'][wn]['roll'] + cur.get('nisa_add_pct', 0))
                cur_basis = '実際の費用（1年ごとの差の平均）＋米国 ETF は取り戻せない外国税と両替'
            for x in lst:
                if x is cur or x.get('nisa_cost') is None:
                    continue
                if frame == 'tsumitate':
                    inframe = bool(x.get('tsumitate'))
                elif frame == 'growth':
                    inframe = bool(x.get('growth'))
                else:
                    inframe = x['vehicle'] in (ideco.get('found_fund_names') or [])
                if not inframe:
                    continue
                wn = '3y' if ('3y' in cur_cost_by and '3y' in x['windows']) else ('2y' if ('2y' in cur_cost_by and '2y' in x['windows']) else None)
                if wn is None:
                    continue
                xc = r3(x['windows'][wn]['roll'] + x.get('nisa_add_pct', 0))
                xs = r3(x['windows'][wn]['slope'] + x.get('nisa_add_pct', 0)) if x['windows'][wn]['slope'] is not None else None
                d_ = r3(cur_cost_by[wn] - xc)
                ok_rk = (x.get('rakuten') or {}).get('sold', False)
                row = {'frame': label, 'current': cur_nm, 'candidate': x['vehicle'], 'window': wn, 'current_cost': cur_cost_by[wn],
                       'candidate_cost': xc, 'candidate_cost_slope': xs, 'cheaper_by': d_, 'rakuten_sold': ok_rk,
                       'rakuten_sales_fee_pct': (x.get('rakuten') or {}).get('sales_fee_pct')}
                if frame != 'ideco':
                    cmp_rows.append(row)
                if d_ is not None and d_ >= 0.10:
                    row2 = dict(row)
                    row2['slope_agrees'] = (xs is not None and cur_cost_by[wn] - xs >= 0.10)
                    named.append(row2)
            D_out.setdefault(bet, {})['current_basis_' + frame] = cur_basis
        if bet == 'NDX':
            D_out.setdefault(bet, {})['ideco_note'] = ('楽天の iDeCo の商品のページで NASDAQ100 の本は「楽天・プラス・NASDAQ-100インデックス・ファンド」だけ'
                                                    f"（ページで見つかった名前 {ideco.get('found_fund_names')}）＝同じ枠の比べる相手が無い")
        D_out.setdefault(bet, {}).update({'index': INDEX_NAME[bet], 'ranking': ranking, 'vs_current': cmp_rows,
                                          'named_cheaper_by_0.10pt_same_frame': named,
                                          'note': None if bet in CURRENT else '今使っている器・予定の器が無い賭け＝0.10pt の名指しの対象なし（並びと表に出ない費用だけ）'})
    hidden = [{'vehicle': x['vehicle'], 'bet': x['bet'], 'window': x['primary_window'], 'stated_fee': x.get('stated_fee_incl_tax'),
               'real_cost_roll': x['real_cost'], 'real_cost_slope': x['real_cost_slope'], 'hidden_roll': x.get('hidden_vs_stated'),
               'hidden_slope': x.get('hidden_vs_stated_slope'), 'slope_agrees': (x.get('hidden_vs_stated_slope') or 0) > 0.2}
              for x in rows if x.get('hidden_vs_stated') is not None and x['hidden_vs_stated'] > 0.2
              and not (x['bet'] == 'SOX' and x.get('kind') == 'us')]   # SMH・SOXX は XSOX と指数が違う＝費用ではない
    idx_diff = [{'vehicle': x['vehicle'], 'why': '指数が XSOX と違う＝この「費用」は指数の差であって費用ではない', 'windows': x['windows']}
                for x in rows if x['bet'] == 'SOX' and x.get('kind') == 'us']

    # ═════════════ F: SMH と SOX の投信 ═════════════
    smh = yahoo_levels('SMH')

    def weekly(lv, a, b):
        ks = sorted(k for k in lv if a <= k <= b)
        out, last = [], None
        for k in ks:
            wk = ymd(k).isocalendar()[:2]
            if last is not None and wk != last[0]:
                out.append(last[1])
            last = (wk, k)
        if last:
            out.append(last[1])
        return out

    def corr_te(a, b, start, end, freq='w'):
        ks = sorted(set(a) & set(b))
        ks = [k for k in ks if start <= k <= end]
        if freq == 'w':
            wk = weekly({k: 1 for k in ks}, start, end)
        elif freq == 'm':
            wk, cur = [], None
            for k in ks:
                if cur is not None and k // 100 != cur // 100:
                    wk.append(cur)
                cur = k
            wk.append(cur)
        else:
            wk = ks
        ra = [math.log(a[y] / a[x]) for x, y in zip(wk, wk[1:])]
        rb = [math.log(b[y] / b[x]) for x, y in zip(wk, wk[1:])]
        per = {'w': 52, 'm': 12, 'd': 252}[freq]
        c = M.corr(ra, rb)
        te = S.stdev([x - y for x, y in zip(ra, rb)]) * math.sqrt(per)
        yrs = (ymd(wk[-1]) - ymd(wk[0])).days / 365.25
        ga = (a[wk[-1]] / a[wk[0]]) ** (1 / yrs) - 1
        gb = (b[wk[-1]] / b[wk[0]]) ** (1 / yrs) - 1
        return {'from': wk[0], 'to': wk[-1], 'n': len(ra), 'months': round(yrs * 12, 1), 'corr': round(c, 4), 'te_pct': round(100 * te, 2),
                'cagr_a_pct': round(100 * ga, 2), 'cagr_b_pct': round(100 * gb, 2), 'gap_pct': round(100 * (ga - gb), 2)}

    ce_ = max(k for k in set(smh) & set(xsox) if k <= END)
    f_corr = {'2012-01〜2026-09（主）': corr_te(smh, xsox, 20120101, END),
              '直近24か月': corr_te(smh, xsox, iymd(datetime.date(ymd(ce_).year - 2, ymd(ce_).month, ymd(ce_).day)), END),
              '直近36か月': corr_te(smh, xsox, iymd(datetime.date(ymd(ce_).year - 3, ymd(ce_).month, ymd(ce_).day)), END)}
    smh_er = smh_issuer if smh_issuer is not None else er_rk.get('SMH')
    sox_funds = [x for x in rows if x['bet'] == 'SOX' and x['kind'] == 'jita']
    f_rows = []
    for x in sox_funds:
        c = x.get('nisa_cost')
        f_rows.append({'fund': x['vehicle'], 'window': x.get('primary_window'), 'real_cost': c, 'real_cost_slope': x.get('real_cost_slope'),
                       'line': r3(smh_er + 0.10), 'cost_ok': (c is not None and c <= smh_er + 0.10),
                       'rakuten_sold': (x.get('rakuten') or {}).get('sold'), 'record': x.get('record')})
    corr_ok = f_corr['2012-01〜2026-09（主）']['corr'] >= 0.98
    any_ok = [r for r in f_rows if r['cost_ok'] and r['rakuten_sold']]
    meth_txt = ''
    try:
        import pypdf
        fetch(SOX_METH, 'Methodology_SOX.pdf', max_age_days=30)
        rd = pypdf.PdfReader(os.path.join(CACHE, 'Methodology_SOX.pdf'))
        meth_txt = re.sub(r'\s+', ' ', ' '.join((p.extract_text() or '') for p in rd.pages))
    except Exception as e:  # noqa
        DEV.append(f'SOX の方法書が取れなかった（{e}）')
    cap = re.search(r'The weights of the top three \(3\) Index Securities.*?respective constraints?\.', meth_txt)
    cap2 = re.search(r'The individual weights of other Index Securities may not exceed 4%[^.]*\.', meth_txt)
    chg = re.search(r'4/22/2024 Constituent Weighting', meth_txt)
    wsb = json.load(open(WHOLE))
    ws = {}
    for wn in ('10年', '15年', '20年'):
        ww = wsb['windows'].get(wn) or {}
        g, gf = ww.get('gap') or {}, ww.get('gapfrac') or {}
        ws[wn] = {'n': ww.get('n'), '1株単位_倍率中央': g.get('倍率_中央'), '端数まで買える_倍率中央': gf.get('倍率_中央'),
                  '1株単位_倍率最悪': g.get('倍率_最悪'), '端数まで買える_倍率最悪': gf.get('倍率_最悪'),
                  '1株単位_ずれ平均の中央pt': g.get('ずれ_平均の中央pt'), '端数まで買える_ずれ平均の中央pt': gf.get('ずれ_平均の中央pt'),
                  '1株単位_ずれ最大の中央pt': g.get('ずれ_最大の中央pt'), '端数まで買える_ずれ最大の中央pt': gf.get('ずれ_最大の中央pt')}
    F_out = {
        'smh_er': {'value_pct': smh_er, 'src': smh_src or '楽天の海外 ETF 一覧（2026-10-11）'},
        'smh_vs_xsox_usd': f_corr,
        'smh_vs_xsox_note': 'SMH＝Yahoo の調整後終値（経費0.35%を引いた後）・XSOX＝指数（費用なし）。週＝ISO 週の最後の取引日。gap は SMH − XSOX の年率',
        'sox_funds_real_cost': f_rows,
        'condition_cost': f'SOX の投信の実際の費用（3年・無ければ2年・1年ごとの差の平均）≤ SMH の経費率 {smh_er}%＋0.10pt＝{r3(smh_er + 0.10)}%',
        'condition_corr': 'SMH と XSOX の週次の相関 ≥ 0.98（24か月以上＝主は 2012-01〜2026-09）',
        'corr_ok': corr_ok,
        'wholeshare_from_out/wholeshare_buy.json': {'note': wsb.get('note'), 'target_etf_side': wsb.get('target_etf_side'), 'windows': ws,
                                                    'reading': '「1株単位（gap＝門の注文書の規則）」と「端数まで買える（gapfrac・参考）」の差が、SOX の投信（円の金額で買える）に替えて取れる上限の目安（同じ指数の場合）'},
        'sox_capping': {'url': SOX_METH, 'top3_rule': cap.group(0) if cap else None, 'others_rule': cap2.group(0) if cap2 else None,
                        'changed_2024_04_22': bool(chg), 'prior_rule_note': '2024-04-22 より前は「1社 8%まで・上位5社だけ 4%を超えてよい」（同じ方法書の変更履歴）' if chg else None,
                        'smh_index_rule': 'SMH の指数（MVIS US Listed Semiconductor 25）の方法書は marketvector.com が 403 で取れず、この道具では確かめていない'},
    }
    F_out['decision'] = ('考える価値あり' if (corr_ok and any_ok) else '考える価値なし（事前登録の2条件を満たさない）')
    F_out['decision_detail'] = {'corr_condition': corr_ok, 'funds_meeting_cost_condition': [r['fund'] for r in f_rows if r['cost_ok']],
                                'funds_meeting_cost_at_rakuten': [r['fund'] for r in any_ok]}

    # ═════════════ G1: SOXX と XSOX ═════════════
    soxx = yahoo_levels('SOXX')
    g1 = {'2021-07〜2026-09（主）': {f: corr_te(soxx, xsox, 20210701, END, f) for f in ('d', 'w', 'm')},
          '参考 2015-01〜2021-06-18（乗り換え前）': {f: corr_te(soxx, xsox, 20150101, 20210618, f) for f in ('d', 'w', 'm')}}
    main_d = g1['2021-07〜2026-09（主）']['d']
    trig = abs(main_d['gap_pct']) > 0.5 or main_d['corr'] < 0.995
    lines = []
    for fn, pat in (('night/bestfund_data.py', r"'SEMI_SOX': \[\('actual', \('yahoo', 'SOXX'\)"), ('night/bestfund_vehicles.py', r"'SEMI_SOX': \('yahoo_er', 'SOXX'"),
                    ('night/bestfund.py', r"HOLD_MAP = \{'SEMI_SOX': 'SOXX'")):
        for i, line in enumerate(open(os.path.join(BASE, fn), encoding='utf-8'), 1):
            if re.search(pat, line):
                lines.append({'file': fn, 'line': i, 'text': line.strip()[:200]})
    G1 = {'what': 'SOXX の配当込み（Yahoo の調整後終値）と XSOX（指数）・主は日次の相関（同じ米国の終値どうし）と年率の差（SOXX − XSOX・SOXX の経費 0.34% を含む）',
          'measure': g1, 'condition': '年率の差の大きさ > 0.5pt か 相関 < 0.995（主の窓・日次）', 'triggered': trig}
    if trig:
        G1['named_non_SOX_after_2021_06'] = [l for l in lines if 'bestfund.py' not in l['file']]
        G1['also_noticed_post_hoc'] = [dict(l, why='bestfund の世界 B は SEMI_SOX を SOXX の保有の業種で作る（事前登録 G1 の外・事後の気づき・直していない）') for l in lines if 'bestfund.py' in l['file']]
        G1['ce_recompute'] = ce_recompute(xsox)
    else:
        G1['named_non_SOX_after_2021_06'] = []

    doc = {
        'generated': datetime.date.today().isoformat(), 'tool': 'night/unx_vehicles.py', 'prereg': PREREG,
        'question': '同じ賭けの器の実際に引かれた費用（D）・SMH と SOX の投信の取り換え（F）・SOXX と XSOX（G1）',
        'scope': '読むだけ。門の採点・四関門・席・売却規律・配分・注文書には触れない',
        'inputs': {
            'XNDX': f'{GIW_URL}（POST id=XNDX・EOD・2015-01-01〜）', 'XSOX': f'{XSOX_CSV}（2001-06-29〜2009-12-21）＋ {GIW_URL}（2009-12-22〜）',
            'XSOX_splice': splice, 'GOLD_index': 'Yahoo GLD の調整後終値＋0.40%/年（1営業日あたり 0.40%/252）',
            'UST20_index': 'Yahoo TLT の調整後終値＋0.15%/年（同上）', 'hedge': f'円ヘッジ＝毎日 −（米国1か月 − 日本1か月）×日数/365（前の日の金利）。米国1か月: {us_src}。日本1か月: 全銀協 日本円 TIBOR 1か月 {TIBOR_URL.format(y="YYYY")}（年ごとの PDF・読めた日数 {jp_used}）',
            'FX': fx_src + '（日本の器の日 d には d より前の最後の値）', 'JITA_NAV': '投資信託協会 投信総合検索ライブラリー /FdsWeb/FDST030000/csv-file-download（nx_jpfunds_data.Lib・トップを読んでから）',
            'JITA_list': f'out/_nx_cache/newfunds/jita_full.json（基準日 {snap_std}・信託報酬・NISA の印・楽天の取扱）', 'JPX': JPX_URL,
            'Rakuten_US_ETF_list': 'out/_nx_cache/newfunds/etfd.csv（2026-10-11）', 'Rakuten_iDeCo': ideco,
            'Yahoo': 'query1.finance.yahoo.com v8 chart（mw_common.yahoo・日次）', 'bestfund': 'out/_mw_cache/bf_chains.json・out/bestfund.json・out/bestfund_persist.json（読むだけ）'},
        'conventions': {
            '実際の費用（roll）': '直近 N 年の中の『1年ごとの差』（器 − 指数の対数の年率）を毎日ずらして平均し、−(exp(平均)−1)（bestfund_vehicles._rolling_td と同じ。1年の窓は1つの差）',
            '実際の費用（slope）': 'log(器 ÷ 指数) を時間（年）に当てた最小二乗の傾き × −1（newfunds._slope）',
            'nisa_cost': '主の窓（3年・無ければ2年）の roll。米国 ETF は取り戻せない配当の外国税（k×dy）と両替 0.02% を足す＝日本の器（基準価額に外国税が入っている）と同じ土俵',
            '判定に使う費用': '事前登録は2つの物差しを挙げ並べ方は1つ＝主は roll（repo の bestfund_vehicles・newfunds と同じ物差し）、slope は名指しの所に並べて食い違いを示す（測る前に決めた・deviations に記録）',
            '表の費用': '日本の投信＝投資信託協会の信託報酬（税抜×1.1）／東証 ETF＝JPX の一覧（税抜×1.1・外国 ETF はそのまま）／米国 ETF＝楽天の一覧の経費率（SMH は VanEck のページ）',
            '同じ枠': 'つみたて＝協会の nisaFlg=1／成長＝協会の nisaGrowthFlg=1（東証 ETF は JPX の NISA の印）・米国 ETF は楽天の一覧にあること／iDeCo＝楽天の iDeCo の商品のページに名前がある本',
            '窓をそろえる': '今の器と候補は同じ長さの窓（両方にあれば3年、無ければ2年）で比べる'},
        'D': {'bets': D_out, 'hidden_cost_over_0.2pt': hidden, 'index_difference_not_cost': idx_diff, 'vehicles': rows, 'not_measured': [
            {'bet': b, 'vehicle': n, 'why': w} for b, n, w in NOT_MEASURED]},
        'F': F_out, 'G1': G1,
    }
    doc['decision'] = {
        'D': {b: {'named_cheaper_same_frame': [f"{x['frame']}: {x['candidate']}（{x['window']} {x['candidate_cost']}% vs 今 {x['current_cost']}%・{x['cheaper_by']}pt 安い"
                                               + ('' if x.get('rakuten_sold') else '・楽天では買えない') + (f"・楽天の販売手数料 {x['rakuten_sales_fee_pct']}%" if x.get('rakuten_sales_fee_pct') else '') + '）'
                                               for x in v['named_cheaper_by_0.10pt_same_frame']],
                  'top3': [f"{r['rank']}. {r['vehicle']}（{r['window']} {r['nisa_cost']}%）" for r in v['ranking'][:3]]} for b, v in D_out.items()},
        'D_hidden_over_0.2pt': [f"{h['vehicle']}（{h['window']} 実際 {h['real_cost_roll']}% − 表 {h['stated_fee']}% = {h['hidden_roll']}pt）" for h in hidden],
        'F': F_out['decision'],
        'G1': ('名指し: ' + '・'.join(f"{l['file']}:{l['line']}" for l in G1['named_non_SOX_after_2021_06'])) if trig else '条件に当たらない（名指しなし）',
    }
    doc['deviations'] = DEV + [
        '事前登録 D の「実際の費用」は回帰の傾きと1年ごとの差の平均の両方を挙げ、並べ方は1つ＝主は1年ごとの差の平均（repo の bestfund_vehicles・newfunds の物差し）と測る前に決めた。傾きは同じ行に並べ、名指しで食い違えばそう書いた',
        '投資信託協会の取得は nx_jpfunds_data.Lib を使った（指示にあった fetch_tsumitate_funds.Lib は User-Agent に個人のメールを載せる＝G3 で名指しされる道具なので使わない。トップを読んでから CSV を取る手順は同じ）',
        '日本1か月は全銀協 日本円 TIBOR 1か月（銀行間の無担保）・米国1か月は米国債1か月（無リスク）＝同じ種類の金利ではない（TIBOR のほうが信用の上乗せの分だけ高い＝ヘッジの費用の近似が小さめ＝ヘッジつきの器の実際の費用が大きめに出る向き）。無料で取れる日本の1か月の日次はこれだけ',
        'SMH の実際の費用は自分の指数（MVIS US Listed Semiconductor 25）の日次が無料で取れない（marketvector.com は 403）ので測れない＝SOX の賭けの今の器の費用は表の経費率＋外国税＋両替で置いた',
        '2632・2569・2087（NASDAQ100 の円ヘッジの東証 ETF）は探索役が名前を挙げて測らなかった本。事前登録の一覧（2841）と同じ賭けとして測った（並びだけ・今の器なし）',
    ]
    doc['caveats'] = [
        '日本の器の基準価額は米国の前日の終値と当日の東京のドル円で決まるが、比べる指数は前の米国営業日の FRED（ニューヨーク正午）のドル円＝日々の差に時刻の雑音が乗る（1年ごとの差の平均と回帰の傾きでならした）',
        '記録の短い器（2年未満）は並びに入れず、1年の窓と設定来の傾きは参考。1年の窓は1つの差なので雑音が大きい（±0.2〜0.5pt）',
        'XSOX の 2009 年以前は NASDAQ の AdditionalData（指数の公表前は後から計算した値の場合があると注記されている）',
        '金の指数は GLD＋0.40%（GLD の経費を足し戻した値）＝金の LBMA 価格そのものではない。東証 1540・1326 は市場価格（基準価額ではない）',
        '円ヘッジの指数は近似（金利差だけ・通貨のベーシスを入れていない）＝ヘッジつきの器の「実際の費用」にはベーシスの分が入る',
        'NISA の枠・楽天の取扱は投資信託協会の一覧（2026-10-09）と JPX・楽天の一覧の写真。変わることがある',
    ]
    doc['runtime_sec'] = round(time.time() - t0)
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    log('→', OUT, doc['runtime_sec'], 's')
    log(json.dumps(doc['decision'], ensure_ascii=False, indent=1))
    return doc


# ═════════════════════════ G1: bestfund の SEMI_SOX を XSOX に差し替えて測り直す ═════════════════════════
def ce_recompute(xsox):
    """out/_mw_cache/bf_chains.json（bestfund が使ったつなぎ）と out/bestfund.json を読むだけ。SEMI_SOX のつなぎの 2021-06 以降を XSOX の月次に替え、
    世界 A1・A2・E（λ×X）とぶれ σ・形 z を作り直して、bestfund.simulate（SEMI_SOX だけ・同じ種）で確実性等価を出す。
    世界 B・C・D はつなぎを使わない（B は SOXX の保有の業種・C は機関の予想・D は割高さ）＝out/bestfund.json の値（小数2桁）をそのまま使う"""
    import numpy as np
    import bestfund as B
    chd = json.load(open(BF_CHAINS))
    bets = chd['bets']
    for b in bets.values():
        for c in ('usd', 'jpy'):
            b[c] = {int(k): v for k, v in b[c].items()}
    bf = json.load(open(BF_OUT))
    row = next(t for t in bf['table'] if t['bet'] == 'SEMI_SOX')
    lam = json.load(open(BF_PERSIST))['lambda_main']['lambda']
    ed = bf['worlds_notes']['E_detail']['SEMI_SOX']
    cost = {b_: D.cost_of(b_, 'best')['total'] for b_ in ('SEMI_SOX', 'SP500')}
    keep = B.BETS
    B.BETS = ['SEMI_SOX']
    try:
        def run(ch_sox):
            ch = {'SP500': bets['SP500'], 'SEMI_SOX': ch_sox}
            a1, _ = B.world_hist(ch, cost, D.A1)
            a2, _ = B.world_hist(ch, cost, D.A2)
            r, q = ch_sox['usd'], bets['SP500']['usd']
            ks = sorted(k for k in r if k in q)
            x = (B.geo(r, ks) - B.geo(q, ks)) - (cost['SEMI_SOX'] - cost['SP500'])
            mu = {'A1': {'SEMI_SOX': a1['SEMI_SOX']}, 'A2': {'SEMI_SOX': a2['SEMI_SOX']},
                  'B': {'SEMI_SOX': row['世界(%/年)']['B'] / 100}, 'C': {'SEMI_SOX': row['世界(%/年)']['C'] / 100},
                  'D': {'SEMI_SOX': row['世界(%/年)']['D'] / 100}, 'E': {'SEMI_SOX': ed['M'] + lam * x}}
            sz = B.sigma_z(ch)
            sims = B.simulate(mu, sz, B.WORLDS)
            sm = B.summarize_bet(sims['SEMI_SOX'], B.WORLDS)
            g1 = B.irr_from_multiple(np.array([B.ce(np.concatenate([sims['SEMI_SOX'][w] for w in B.WORLDS]), 1)]))[0]
            g5 = B.irr_from_multiple(np.array([B.ce(np.concatenate([sims['SEMI_SOX'][w] for w in B.WORLDS]), 5)]))[0]
            return {'CE_γ2': round(100 * sm['ce_irr'], 3), 'CE_γ1': round(100 * g1, 3), 'CE_γ5': round(100 * g5, 3),
                    'worlds_pct': {w: round(100 * mu[w]['SEMI_SOX'], 3) for w in B.WORLDS}, 'X': round(x, 5),
                    'sigma_pct': round(100 * sz['SEMI_SOX'][0], 2), 'P15': round(sm['p_ge15'], 3), 'median': round(100 * sm['median_irr'], 3)}
        orig = bets['SEMI_SOX']
        base = run(orig)
        # XSOX の月末の水準 → 月次
        me = {}
        for k in sorted(xsox):
            if k <= END:
                me[k // 100] = xsox[k]
        ms = sorted(me)
        xm = {b_: me[b_] / me[a_] - 1 for a_, b_ in zip(ms, ms[1:]) if (b_ // 100 * 12 + b_ % 100) - (a_ // 100 * 12 + a_ % 100) == 1}
        fxchg = {k: (1 + orig['jpy'][k]) / (1 + orig['usd'][k]) - 1 for k in orig['usd'] if k in orig['jpy']}

        def sub(frm):
            usd = dict(orig['usd'])
            n = 0
            for k in list(usd):
                if k >= frm and k in xm:
                    usd[k] = xm[k]; n += 1
            jpy = {k: (1 + v) * (1 + fxchg[k]) - 1 for k, v in usd.items() if k in fxchg}
            return {'usd': usd, 'jpy': jpy}, n
        ch1, n1 = sub(202106)
        ch2, n2 = sub(200107)
        s1, s2 = run(ch1), run(ch2)
        elig = [t for t in bf['table'] if t['eligible'] and t['bet'] != 'SEMI_SOX']

        def rank(ce_):
            return 1 + sum(1 for t in elig if t['CE_γ2(%/年)'] > ce_)
        res = {
            'how': '世界 A1・A2・E と σ・z を作り直し、B・C・D は out/bestfund.json の SEMI_SOX の値（小数2桁）。模擬は bestfund.simulate を SEMI_SOX だけで（同じ種＝他の賭けの数字は out/bestfund.json のまま比べられる）',
            'published': {'CE_γ2': row['CE_γ2(%/年)'], 'rank_eligible': row['rank_eligible'], 'worlds_pct': row['世界(%/年)'], 'sigma_pct': row['σ(円・%/年)'],
                          'E_X': ed['X'], 'chain': row['つなぎ']},
            'reproduced_original': dict(base, rank_eligible=rank(base['CE_γ2'])),
            'reproduction_check': {'CE_diff_pt': round(base['CE_γ2'] - row['CE_γ2(%/年)'], 3), 'X_diff': round(base['X'] - ed['X'], 5),
                                   'A1_diff_pt': round(base['worlds_pct']['A1'] - row['世界(%/年)']['A1'], 3),
                                   'A2_diff_pt': round(base['worlds_pct']['A2'] - row['世界(%/年)']['A2'], 3),
                                   'ok': abs(base['CE_γ2'] - row['CE_γ2(%/年)']) <= 0.02},
            'substituted_from_2021_06（主）': dict(s1, months_replaced=n1, rank_eligible=rank(s1['CE_γ2'])),
            'substituted_from_2001_07（感度・XSOX のある全期間）': dict(s2, months_replaced=n2, rank_eligible=rank(s2['CE_γ2'])),
            'n_eligible': len(elig) + 1,
            'note': '参考（事前登録 G1 の「参考・別の出力へ」）。out/bestfund.json は書き換えていない。世界 B の SOXX の保有の業種はそのまま（事後の気づき）',
        }
        return res
    finally:
        B.BETS = keep


if __name__ == '__main__':
    main()
