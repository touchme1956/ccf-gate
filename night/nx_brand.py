#!/usr/bin/env python3
"""night/nx_brand.py — nx 角度 brand の測定（読むだけ・門の判定には不使用）

外部の格付けの一覧（Interbrand『Best Global Brands』・Fortune『World's Most Admired Companies』・
Forbes『World's Most Innovative Companies』）に載った会社を、一覧の公開の後の最初の月末に買って
次の一覧まで持つと、市場（SPY / Ken French の Developed 市場）に勝てるか。

事前登録: out/nx_brand_prereg.json（測る前に固定・書き換えない）／全体の線: out/nx_prereg.json（criteria_short_sample）
一覧と対応表: out/_nx_cache/nx_brand_lists.json（night/nx_brand_data.py が作る。lists_sha256 が事前登録と一致しなければ止まる）
株価: Yahoo の月次の調整後終値（nx_common.yahoo と同じキャッシュ名）。米国外はドルに直す。
統計・格付け: nx_common.excess_stats / holm / p_one / grade_short / apply_cost をそのまま使う。

使い方:
  python3 night/nx_brand.py --fetch      株価・為替・日次（分離の月の検査用）を取ってキャッシュへ（成績は計算しない）
  python3 night/nx_brand.py --coverage   被覆だけ（どの親会社に値があるか・上場前・値の無い上場会社）を表示（成績は計算しない）
  python3 night/nx_brand.py              全規則を測って out/nx_brand.json へ（tested に主4・探索12・報告 R1〜R9 を1本残らず）
"""
import sys, os, json, math, re, time, datetime, urllib.request, urllib.error, urllib.parse, statistics as S

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N  # noqa: E402
import nx_brand_data as B  # noqa: E402

PRE_P = os.path.join(N.BASE, 'out', 'nx_brand_prereg.json')
LISTS_P = os.path.join(N.CACHE, 'nx_brand_lists.json')
OUT_NAME = 'nx_brand.json'
END = 202608          # French と揃える（2026-09 は月の途中で使わない）
LB_HIT = -0.30        # 上場廃止の下限版: 途切れた月に −30%
COST = {'us': 0.0020, 'global': 0.0030}          # 片道の回転 100% あたり（事前登録）
COST_SENS = {'us': 0.00495, 'global': 0.0060}   # R7 感度


# ───────────────────────── 事前登録と一覧 ─────────────────────────
def load_lists():
    pre = json.load(open(PRE_P))
    o = json.load(open(LISTS_P))
    o['interbrand']['years'] = {int(k): v for k, v in o['interbrand']['years'].items()}
    o['wmac'] = {int(k): v for k, v in o['wmac'].items()}
    o['forbes'] = {int(k): v for k, v in o['forbes'].items()}
    want = pre['tools']['lists_sha256']
    got = B.lists_sha(o)
    if got != want or o.get('lists_sha256') != want:
        raise SystemExit(f'lists_sha256 が事前登録と違う: 登録 {want} / 再計算 {got} / ファイル {o.get("lists_sha256")} → 止まる')
    return pre, o, got


# ───────────────────────── 株価（Yahoo） ─────────────────────────
def _yh_name(tk, interval):
    return f'yh_{tk.replace("^", "IDX_").replace("=", "_")}_{interval}.json'


def yh_json(tk, interval='1mo', fetch=True):
    """Yahoo の chart API の生 JSON（nx_common.yahoo と同じキャッシュ名）。404（上場廃止・記号なし）は .none を置いて以後は取りに行かない"""
    p = os.path.join(N.CACHE, _yh_name(tk, interval))
    neg = p + '.none'
    if os.path.exists(neg):
        return None
    if os.path.exists(p) and os.path.getsize(p) > 0:
        try:
            return json.load(open(p))
        except ValueError:
            pass
    if not fetch:
        return None
    u = (f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(tk)}?period1=0&period2={int(time.time())}'
         f'&interval={interval}&events=div%2Csplit')
    for i in range(4):
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers=N.UA), timeout=60).read()
            os.makedirs(N.CACHE, exist_ok=True)
            tmp = f'{p}.{os.getpid()}.tmp'
            open(tmp, 'wb').write(b)
            os.replace(tmp, p)
            time.sleep(0.25)
            return json.loads(b)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                open(neg, 'w').write(f'404 {datetime.datetime.utcnow().isoformat()}')
                return None
            time.sleep(2 ** (i + 1))
        except Exception:  # noqa
            time.sleep(2 ** (i + 1))
    return None


PX = {}


def series(tk, fetch=False):
    """→ {'px': {yyyymm: 調整後終値}, 'close': {...}, 'ccy': 通貨, 'first': 最初の月, 'last': 最後の月（≤END）} か None"""
    if tk in PX:
        return PX[tk]
    j = yh_json(tk, '1mo', fetch=fetch)
    out = None
    if j and (j.get('chart') or {}).get('result'):
        r = j['chart']['result'][0]
        ts = r.get('timestamp') or []
        ind = r.get('indicators') or {}
        adj = (ind.get('adjclose') or [{}])[0].get('adjclose') or (ind.get('quote') or [{}])[0].get('close') or []
        cl = (ind.get('quote') or [{}])[0].get('close') or []
        px, close = {}, {}
        for t, a, c in zip(ts, adj, cl + [None] * (len(ts) - len(cl))):
            # 月の足の時刻は取引所の現地の 1日 0時（東京なら前日 15時 UTC・ロンドンの夏時間なら前日 23時 UTC）。
            # UTC のまま月を読むと米国外の系列が 1か月前にずれる（先読み）ので、12時間足してから月を読む
            d = datetime.datetime.utcfromtimestamp(t + 43200)
            k = d.year * 100 + d.month
            if k > END:
                continue
            if a is not None and a > 0:
                px[k] = a
            if c is not None and c > 0:
                close[k] = c
        if px:
            out = {'px': px, 'close': close, 'ccy': (r.get('meta') or {}).get('currency'), 'first': min(px), 'last': max(px),
                   'events': r.get('events') or {}}
    PX[tk] = out
    return out


def fx_series(ccy, fetch=False):
    """1 単位の現地通貨 = 何ドル（月末）。{CCY}USD=X、無ければ USD{CCY}=X の逆数、無ければ {CCY}=X（Yahoo の USD 建て）の逆数"""
    if ccy in (None, 'USD'):
        return None
    c = 'GBP' if ccy in ('GBp', 'GBX') else ccy
    if c in FXC:
        return FXC[c]
    for tk, inv in ((f'{c}USD=X', False), (f'USD{c}=X', True), (f'{c}=X', True)):
        s = series(tk, fetch=fetch)
        if s:
            src = s['close'] or s['px']
            fx = {k: (1 / v if inv else v) for k, v in src.items() if v}
            # データの誤りの訂正: Yahoo の月足の為替には桁の壊れた月がある（実測 KRWUSD=X 2015-02 が 9.07＝本来 0.00091、TWDUSD=X 2014-12）。
            # 同じ記号の日足から『その月の日々の値の中央値から ±20% に入る最後の日』の値を作り、月足と 3% 超ずれる月は日足の値に置き換える
            d = daily_month_end(tk)
            fixes = []
            if d:
                for k, v in d.items():
                    v = 1 / v if inv else v
                    if k in fx and abs(fx[k] / v - 1) > 0.03:
                        fixes.append((k, fx[k], v))
                        fx[k] = v
                    elif k not in fx and k <= END:
                        fixes.append((k, None, v))
                        fx[k] = v
            FXC[c] = {'tk': tk, 'inv': inv, 'fx': fx, 'fixes': fixes}
            return FXC[c]
    return None


FXC = {}


def daily_month_end(tk):
    """日足の終値から月末の値（その月の日々の値の中央値から ±20% に入る最後の日）"""
    j = yh_json(tk, '1d', fetch=True)
    if not j or not (j.get('chart') or {}).get('result'):
        return None
    r = j['chart']['result'][0]
    ts = r.get('timestamp') or []
    cl = ((r.get('indicators') or {}).get('quote') or [{}])[0].get('close') or []
    off = int((r.get('meta') or {}).get('gmtoffset') or 0)
    bym = {}
    for t, v in zip(ts, cl):
        if v is None or v <= 0:
            continue
        d = datetime.datetime.utcfromtimestamp(t + off)   # 日足の時刻は取引所の寄り付き（ニューヨークは UTC 13:30）＝現地の時刻で日付を読む
        bym.setdefault(d.year * 100 + d.month, []).append(v)
    out = {}
    for k, vs in bym.items():
        med = S.median(vs)
        good = [v for v in vs if abs(v / med - 1) < 0.2]
        if good:
            out[k] = good[-1]
    return out


def ym_prev(ym):
    return ym - 1 if ym % 100 > 1 else (ym // 100 - 1) * 100 + 12


def ym_next(ym):
    return ym + 1 if ym % 100 < 12 else (ym // 100 + 1) * 100 + 1


def ym_range(a, z):
    out, k = [], a
    while k <= z:
        out.append(k)
        k = ym_next(k)
    return out


RET = {}
FXM = {}


def usd_returns(tk):
    """ドル建ての月次リターン {yyyymm: r}（前の値のある月から）。gap: 抜けた月の集合。None = 値が無い"""
    if tk in RET:
        return RET[tk]
    s = series(tk)
    if not s:
        RET[tk] = None
        return None
    ks = sorted(s['px'])
    fx = fx_series(s['ccy']) if s['ccy'] not in (None, 'USD') else None
    if s['ccy'] not in (None, 'USD') and not fx:
        RET[tk] = None
        return None
    r, gaps = {}, []
    for p, k in zip(ks, ks[1:]):
        x = s['px'][k] / s['px'][p] - 1
        if fx:
            f0, f1 = fx['fx'].get(p), fx['fx'].get(k)
            if not f0 or not f1:
                continue
            x = (1 + x) * (f1 / f0) - 1
        r[k] = x
        if ym_next(p) != k:
            gaps.append((p, k))
    if fx:
        FXM[fx['tk']] = set(fx['fx'])
    out = {'r': r, 'first': ks[0], 'last': ks[-1], 'px_months': set(ks), 'gaps': gaps, 'ccy': s['ccy'],
           'fx': (fx or {}).get('tk')}
    RET[tk] = out
    return out


# ───────────────────────── 一覧 → 持つもの（買う月ごと） ─────────────────────────
# WMAC の候補のうち、一度も上場していない会社（相互会社・協同組合・パートナーシップ・従業員所有）＝買えない＝どの版でも母集団から外す。
# Fortune の会社ページの Company type は『今』の種類（買収された会社も 'Private'）なので使えず、測る前に名前で固定した（成績は見ていない）。
WMAC_NEVER_LISTED = {
    '/company/graybar-electric/', '/company/jones-financial/', "/company/land-o-lakes/", '/company/liberty-mutual-insurance-group/',
    '/company/massachusetts-mutual-life-insurance/', '/company/nationwide/', '/company/new-york-life-insurance/',
    '/company/northwestern-mutual/', '/company/peter-kiewit-sons/', '/company/publix-super-markets/', '/company/state-farm-insurance/',
    '/company/tiaa/', '/company/thrivent-financial/', '/company/usaa/', '/company/ch2m-hill/',
}
WMAC_NEVER_LISTED_NAMES = {  # slug が上と違っていても名前で拾う（小文字の部分一致）
    'graybar', 'jones financial', "land o'lakes", 'liberty mutual', 'massachusetts mutual', 'nationwide', 'new york life', 'northwestern mutual',
    "peter kiewit", 'publix', 'state farm', 'tiaa', 'thrivent', 'united services automobile', 'ch2m hill',
}

PRE_IPO = {}   # {鍵: 上場月}。--coverage の結果（系列の始まり > 買う月）を見て、本当に上場前のものだけを下で固定する


def _never_listed_wmac(row):
    n = (row['name'] or '').lower()
    return row['slug'] in WMAC_NEVER_LISTED or any(x in n for x in WMAC_NEVER_LISTED_NAMES)


def _parse_chg(s):
    if s is None:
        return None, False
    t = str(s).strip().lower()
    if t.startswith('new') or t in ('n/a', 'na', '-', ''):
        return None, t.startswith('new')
    m = re.match(r'^([+\-−]?\d+(?:\.\d+)?)\s*%$', t.replace('−', '-'))
    return (float(m.group(1)) / 100, False) if m else (None, False)


def ib_prev_values(o, y):
    """前年の値: 我々の前年の完全な一覧（あれば）→ 無ければ Interbrand の API の前年（生き残り）。{正規化した名前: 値}"""
    yrs = o['interbrand']['years']
    used = {x['list_year'] for x in o['interbrand']['schedule'] if x['used']}
    if (y - 1) in used:
        return {B.norm(r['name']): r['value'] for r in yrs[y - 1]['rows'] if r.get('name') and r.get('value')}, 'complete'
    return {B.norm(r['name']): r['value'] for r in B.ib_api(y - 1) if r.get('value')}, 'api_prev'


def ib_forms(o, universe='us', rank_max=None, pick=None, uniform_nov=False, list_src='complete'):
    """Interbrand の持つもの。universe: 'us' | 'global' | 'nonus'。pick: None | 'risers' | 'fallers'。
    list_src: 'complete'（当時の原本で組んだ 17年分）| 'api_survivor'（R1: 2007〜2019 の API の生き残り・2015/2017 を含む）| 'api_2001_2006'（R2）"""
    P = o['parents']
    forms = []
    if list_src == 'complete':
        sched = [x for x in o['interbrand']['schedule'] if x['used']]
        plan = []
        for i, x in enumerate(sched):
            y = x['list_year']
            if uniform_nov:
                M = y * 100 + 11
                H = sched[i + 1]['list_year'] * 100 + 11 if i + 1 < len(sched) else END
            else:
                M, H = x['buy_month'], x['hold_last_month'] or END
            plan.append((y, M, H, o['interbrand']['years'][y]['rows']))
    elif list_src == 'api_survivor':
        sched = {x['list_year']: x for x in o['interbrand']['schedule'] if x['used']}
        ys = list(range(2007, 2026))
        bm = {y: (sched[y]['buy_month'] if y in sched else y * 100 + 10) for y in ys}   # 2015・2017 は 10月（報告のみ）
        plan = []
        for i, y in enumerate(ys):
            H = bm[ys[i + 1]] if i + 1 < len(ys) else END
            rows = [dict(r, src='api', owner=B.ib_owner(r['name'], bm[y])) for r in B.ib_api(y)]
            plan.append((y, bm[y], H, rows))
    elif list_src == 'api_2001_2006':
        ys = list(range(2001, 2007))
        plan = []
        for i, y in enumerate(ys):
            M = y * 100 + 10
            H = ys[i + 1] * 100 + 10 if i + 1 < len(ys) else 200708
            rows = [dict(r, src='api', owner=B.ib_owner(r['name'], M)) for r in B.ib_api(y)]
            plan.append((y, M, H, rows))
    else:
        raise ValueError(list_src)
    for y, M, H, rows in plan:
        hold, unmapped = {}, []
        for r in rows:
            pid = B.ib_owner(r['name'], M) if (uniform_nov and r.get('name')) else r.get('owner')
            if pid is None:
                unmapped.append(r.get('name'))
                continue
            pp = P.get(pid) or {}
            if pid != 'PRIVATE':
                if universe == 'us' and not pp.get('us'):
                    continue
                if universe == 'nonus' and pp.get('us'):
                    continue
            if rank_max and (r.get('rank') or 999) > rank_max:
                continue
            h = hold.setdefault(pid, {'cands': list(pp.get('yahoo') or []), 'status': 'private' if pid == 'PRIVATE' else 'listed',
                                      'val': 0.0, 'grid_val': 0.0, 'rows': [], 'label': pp.get('name'), 'old': (o['old_ticker'].get(pid))})
            v = float(r.get('value') or 0)
            h['val'] += v
            if r.get('src') == 'pdf_grid_value':
                h['grid_val'] += v
            h['rows'].append((r.get('rank'), r.get('name'), r.get('src'), r.get('chg')))
        if 'PRIVATE' in hold:
            hold['PRIVATE']['status'] = 'private'
        if pick:
            prev, prev_how = ib_prev_values(o, y)
            yo = {}
            for pid, h in hold.items():
                if h['status'] != 'listed':
                    continue
                num = den = 0.0
                for (rk, nm, src, chg) in h['rows']:
                    v = next((float(r.get('value') or 0) for r in rows if r.get('name') == nm), 0.0)
                    g, is_new = _parse_chg(chg)
                    if g is None and not is_new:
                        pv = prev.get(B.norm(nm or ''))
                        g = (v / pv - 1) if pv else None
                    if g is None or not v:
                        continue
                    num += v * g
                    den += v
                if den:
                    yo[pid] = num / den
            order = sorted(yo, key=lambda k: (-yo[k], k))
            k3 = int(round(len(order) / 3.0))
            keep = set(order[:k3]) if pick == 'risers' else set(order[len(order) - k3:])
            hold = {k: v for k, v in hold.items() if k in keep}
            for k in hold:
                hold[k]['yoy'] = yo[k]
        forms.append({'list': 'IB', 'list_year': y, 'buy': M, 'last': H, 'hold': hold, 'unmapped': unmapped})
    return forms


def wmac_forms(o, universe='us', subset='allstars'):
    wm = o['wmac']
    forms = []
    for y in sorted(wm):
        v = wm[y]
        M, H = v['buy_month'], v['hold_last_month'] or END
        rows = v['rows']
        if subset == 'laggards':
            worst = {}
            for r in rows:
                if r.get('industry') and r.get('industry_rank'):
                    worst[r['industry']] = max(worst.get(r['industry'], 0), r['industry_rank'])
        hold = {}
        for r in rows:
            a = r.get('allstar_rank')
            if subset == 'allstars' and not a:
                continue
            if subset == 'top10' and not (a and a <= 10):
                continue
            if subset == 'contenders' and a:
                continue
            if subset == 'leaders' and r.get('industry_rank') != 1:
                continue
            if subset == 'laggards' and not (r.get('industry_rank') and r['industry_rank'] == worst.get(r.get('industry'))):
                continue
            if universe == 'us' and not r.get('us'):
                continue
            key = r['slug']
            st = 'private' if _never_listed_wmac(r) else 'listed'
            hold[key] = {'cands': [r['yahoo']] if r.get('yahoo') else [], 'status': st, 'val': 1.0, 'grid_val': 0.0,
                         'rows': [(a, r['name'], r.get('industry'), r.get('industry_rank'))], 'label': r['name'],
                         'old': o['wmac_old_ticker'].get(key)}
        forms.append({'list': 'WMAC', 'list_year': y, 'buy': M, 'last': H, 'hold': hold, 'unmapped': []})
    if subset in ('leaders', 'laggards'):
        forms = [f for f in forms if f['list_year'] >= 2016]   # 業種内順位は 2016〜
    return forms


def forbes_forms(o):
    fb = o['forbes']
    forms = []
    for y in sorted(fb):
        v = fb[y]
        if not v['usable']:
            continue
        hold = {}
        for r in v['rows']:
            if not r.get('us'):
                continue
            hold[r['name']] = {'cands': [r['yahoo']] if r.get('yahoo') else [], 'status': 'listed', 'val': 1.0, 'grid_val': 0.0,
                               'rows': [(r['rank'], r['name'], r.get('industry'), r.get('innovation_premium'))], 'label': r['name'], 'old': None}
        forms.append({'list': 'FORBES', 'list_year': y, 'buy': v['buy_month'], 'last': v['hold_last_month'], 'hold': hold, 'unmapped': []})
    return forms


# ───────────────────────── 記号の解決（買う月に値があるか） ─────────────────────────
AV_NOTE = []


def av_returns(sym, last_month):
    """上場廃止した米国の親会社の Alpha Vantage 月次調整後（事前登録の delisted_fallback）。
    MCP で取った結果を out/_nx_cache/av_{記号}_monthly_adj.json に置いたときだけ使う（無ければ None）。
    系列の最後の月が上場廃止の月と ±1か月で一致するときだけ採用"""
    p = os.path.join(N.CACHE, f'av_{sym}_monthly_adj.json')
    if not os.path.exists(p):
        return None
    j = json.load(open(p))
    ts = j.get('Monthly Adjusted Time Series') or {}
    px = {}
    for d, row in ts.items():
        k = int(d[:4]) * 100 + int(d[5:7])
        a = float(row.get('5. adjusted close') or 0)
        if a > 0 and k <= END:
            px[k] = a
    if not px:
        return None
    lk = max(px)
    if abs((lk // 100 * 12 + lk % 100) - (last_month // 100 * 12 + last_month % 100)) > 1:
        AV_NOTE.append(f'{sym}: AV の最後の月 {lk} が上場廃止の月 {last_month} と ±1 か月で一致しない＝使わない')
        return None
    ks = sorted(px)
    return {'r': {k: px[k] / px[p0] - 1 for p0, k in zip(ks, ks[1:])}, 'first': ks[0], 'last': ks[-1], 'px_months': set(ks), 'gaps': [],
            'ccy': 'USD', 'fx': None}


def _avail_at(u, M):
    if not u or M not in u['px_months']:
        return False
    return True if not u.get('fx') else (M in (u.get('fx_months') or u['px_months']))


def resolve(fkey, h, M):
    """→ (状態, 記号)。状態: ok / private / pre_ipo / missing"""
    if h['status'] == 'private':
        return 'private', None
    if PRE_IPO.get(fkey, 0) > M:
        return 'pre_ipo', None
    for tk in h['cands']:
        u = usd_returns(tk)
        if u and M in u['px_months'] and (u['first'] <= M):
            if u.get('fx') and M not in FXM.get(u['fx'], set()):
                continue
            return 'ok', tk
    old = h.get('old')
    if old and old[2] != 'reused':
        u = av_returns(old[0], old[1])
        if u and M in u['px_months']:
            RET['AV:' + old[0]] = u
            return 'ok', 'AV:' + old[0]
    return 'missing', None




# ───────────────────────── 取得（成績は計算しない） ─────────────────────────
ETFS = ['SPY', 'OEF', 'RSP', 'MGC', 'QQQ', 'IOO', 'ACWI', 'MOAT']


def all_forms(o):
    F = {
        'P1': ib_forms(o, 'us'), 'P3': ib_forms(o, 'global'), 'P4': wmac_forms(o, 'us', 'allstars'),
        'E1': ib_forms(o, 'us', rank_max=50), 'E2': ib_forms(o, 'us', pick='risers'), 'E3': ib_forms(o, 'us', pick='fallers'),
        'E5': ib_forms(o, 'us', uniform_nov=True), 'E6': wmac_forms(o, 'us', 'top10'), 'E7': wmac_forms(o, 'global', 'allstars'),
        'E8': wmac_forms(o, 'us', 'contenders'), 'E10': wmac_forms(o, 'us', 'leaders'), 'E11': wmac_forms(o, 'us', 'laggards'),
        'E12': forbes_forms(o), 'R1': ib_forms(o, 'us', list_src='api_survivor'), 'R2': ib_forms(o, 'us', list_src='api_2001_2006'),
        'NONUS': ib_forms(o, 'nonus'),
    }
    return F


def fetch(o):
    F = all_forms(o)
    tks = set(ETFS)
    for fs in F.values():
        for f in fs:
            for h in f['hold'].values():
                tks.update(h['cands'])
    tks = sorted(tks)
    print('記号', len(tks))
    for i, tk in enumerate(tks):
        j = yh_json(tk, '1mo', fetch=True)
        if i % 25 == 0:
            print(i, tk, 'ok' if j else 'none', flush=True)
    ccys = set()
    for tk in tks:
        s = series(tk)
        if s and s['ccy'] not in (None, 'USD'):
            ccys.add(s['ccy'])
    print('通貨', sorted(ccys))
    for c in sorted(ccys):
        fx = fx_series(c, fetch=True)
        print(c, fx and fx['tk'], fx and min(fx['fx']))


# ───────────────────────── 分離（spin-off）の手直し ─────────────────────────
SPIN_FIX = {}   # {記号: {月: 置き換えるドル建てリターン}}（Yahoo が分離を反映していないと確かめた月だけ・下の spin_check が作る）


def ret_of(tk, t):
    fx = SPIN_FIX.get(tk)
    if fx and t in fx:
        return fx[t]
    u = RET.get(tk) if tk.startswith('AV:') else usd_returns(tk)
    return None if not u else u['r'].get(t)


BAD_MONTH = {}  # {記号: {月}}: 月次と日次が食い違い『データの誤り』と確かめた月（値の無い月として扱う）


# ───────────────────────── ポートフォリオ ─────────────────────────
def simulate(forms, bench, mode='base', weights='ew', exclude=frozenset(), grid_bench=False, z=END):
    """forms を順に買い直す。mode: base（値の無い親会社は外す・途切れたら現金）| lower（途切れた月に −30%・以後 0%・買う月に値の無い上場会社も −30%）
    | neutral（値の無い・途切れた後は相手と同じ）。weights: ew | bvw。grid_bench: R6（手がかり由来の名前の行の分は相手と同じ）。
    → {'r': {月: リターン}, 'contrib': {鍵: Σ w(r−b)}, 'turn': [(買う月, 片道の回転)], 'forms': [...]}"""
    R, contrib, turns, finfo = {}, {}, [], []
    prev = None   # 前の保有の、次の買う月の月末の重み {位置: 重み}
    for f in forms:
        M, H = f['buy'], min(f['last'], z)
        if M >= z:
            break
        mem, dropped = {}, {'private': [], 'pre_ipo': [], 'missing': []}
        for key, h in f['hold'].items():
            if key in exclude:
                continue
            st, tk = resolve(key, h, M)
            if st == 'ok':
                mem[key] = {'tk': tk, 'state': 'live'}
            elif st == 'missing':
                dropped['missing'].append(key)
                if mode in ('lower', 'neutral'):
                    mem[key] = {'tk': None, 'state': 'missing'}
            else:
                dropped[st].append(key)
        if not mem:
            raise SystemExit(f'{f["list"]} {f["list_year"]}: 持つものが無い')
        raw = {k: (1.0 if weights == 'ew' else f['hold'][k]['val']) for k in mem}
        tot = sum(raw.values())
        assert tot > 0 and all(v >= 0 for v in raw.values())
        pos = {}   # 位置の鍵 → (重み, 状態, 記号, 親の鍵)
        for k, m in mem.items():
            w = raw[k] / tot
            gfrac = 0.0
            if grid_bench:
                h = f['hold'][k]
                gfrac = (h['grid_val'] / h['val'] if h['val'] else 0.0) if weights == 'bvw' else (1.0 if h['grid_val'] >= h['val'] - 1e-9 else 0.0)
            if gfrac < 1:
                pos[('s', k)] = [w * (1 - gfrac), m['state'], m['tk'], k]
            if gfrac > 0:
                pos[('g', k)] = [w * gfrac, 'bench', None, k]
        if prev is None:
            to = 1.0
        else:
            keys = set(prev) | set(pos)
            to = 0.5 * sum(abs(pos.get(q, [0])[0] - prev.get(q, 0.0)) for q in keys)
        assert abs(sum(p[0] for p in pos.values()) - 1) < 1e-9, '買う月の重みの和が 1 でない'
        assert -1e-9 <= to <= 1 + 1e-9, f'回転が 0〜1 の外 {to}'
        turns.append((M, round(to, 4)))
        vlist = {k: f['hold'][k]['val'] for k in f['hold']}
        finfo.append({'list_year': f['list_year'], 'buy': M, 'last': H, 'n_held': len(mem),
                      'n_live': sum(1 for m in mem.values() if m['state'] == 'live'),
                      'dropped': {a: sorted(map(str, b)) for a, b in dropped.items() if b},
                      'value_share_missing': round(sum(vlist.get(k, 0) for k in dropped['missing']) / (sum(vlist.values()) or 1), 4) if weights == 'bvw' else None,
                      'turnover': round(to, 4)})
        for t in ym_range(ym_next(M), H):
            b = bench.get(t)
            if b is None:
                raise SystemExit(f'相手の {t} が無い')
            rt, rs = 0.0, {}
            for q, p in pos.items():
                w, st, tk, k = p
                if st == 'live':
                    x = ret_of(tk, t)
                    bad = t in BAD_MONTH.get(tk, ())
                    if x is None or bad:
                        u = RET.get(tk) if tk.startswith('AV:') else usd_returns(tk)
                        later = [k2 for k2 in u['r'] if t < k2 <= H] if (u and not bad) else []
                        if later:          # データの抜け（後で値が戻る）＝その月は 0、戻った月に抜けた間の動きをまとめて受ける
                            x = 0.0
                        else:              # 途切れた（上場廃止・データの終わり・データの誤り）
                            if mode == 'base':
                                x, p[1] = 0.0, 'cash'
                            elif mode == 'lower':
                                x, p[1] = LB_HIT, 'cash'
                            else:
                                x, p[1] = b, 'bench'
                elif st == 'missing':
                    if mode == 'lower':
                        x, p[1] = LB_HIT, 'cash'
                    else:
                        x, p[1] = b, 'bench'
                elif st == 'cash':
                    x = 0.0
                else:   # bench
                    x = b
                rs[q] = x
                rt += w * x
                contrib[k] = contrib.get(k, 0.0) + w * (x - b)
            R[t] = rt
            for q, p in pos.items():
                p[0] = p[0] * (1 + rs[q]) / (1 + rt) if rt > -1 else 0.0
        prev = {}
        for q, p in pos.items():
            qq = q if p[1] == 'live' else (p[1], q)
            prev[qq] = prev.get(qq, 0.0) + p[0]
    return {'r': R, 'contrib': contrib, 'turn': turns, 'forms': finfo}


def halves(r, a, z):
    ks = [k for k in sorted(r) if a <= k <= z]
    n = len(ks)
    h = n // 2
    return (ks[0], ks[h - 1]), (ks[h], ks[-1])


def annual_turnover(sim, a, z):
    tot = sum(to for (M, to) in sim['turn'] if a <= ym_next(M) <= z)
    months = len([k for k in sim['r'] if a <= k <= z])
    return tot / (months / 12.0) if months else 0.0


def by_year(sim, bench):
    out = []
    for f in sim['forms']:
        ks = [k for k in ym_range(ym_next(f['buy']), f['last']) if k in sim['r']]
        if not ks:
            continue
        gs = math.prod(1 + sim['r'][k] for k in ks) - 1
        gb = math.prod(1 + bench[k] for k in ks) - 1
        out.append({'list_year': f['list_year'], 'from': ks[0], 'to': ks[-1], 'months': len(ks), 'rule': round(gs * 100, 2),
                    'bench': round(gb * 100, 2), 'diff': round((gs - gb) * 100, 2), 'n_held': f['n_held'], 'n_live': f['n_live']})
    return out


# ───────────────────────── 因子の切片（R4） ─────────────────────────
def ols_nw(y, X, lag=12):
    import numpy as np
    y = np.asarray(y, float)
    X = np.asarray(X, float)
    n, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    e = y - X @ b
    U = X * e[:, None]
    Sg = U.T @ U
    for L in range(1, lag + 1):
        G = U[L:].T @ U[:-L]
        Sg += (1 - L / (lag + 1)) * (G + G.T)
    V = XtX_inv @ Sg @ XtX_inv
    se = np.sqrt(np.diag(V))
    r2 = 1 - (e @ e) / (((y - y.mean()) ** 2).sum())
    return b, se, r2


FACT = {}


def factors(region):
    if region in FACT:
        return FACT[region]
    if region == 'us':
        t5 = next(v for k, v in N.french_tables('F-F_Research_Data_5_Factors_2x3').items() if v['freq'] == 'monthly')
        tm = next(v for k, v in N.french_tables('F-F_Momentum_Factor').items() if v['freq'] == 'monthly')
    else:
        t5 = next(v for k, v in N.french_tables('Developed_5_Factors').items() if v['freq'] == 'monthly')
        tm = next(v for k, v in N.french_tables('Developed_Mom_Factor').items() if v['freq'] == 'monthly')
    cols = [c.strip() for c in t5['cols']]
    out = {}
    for d, row in t5['data'].items():
        m = tm['data'].get(d)
        if m is None or m[0] is None or any(x is None for x in row):
            continue
        rec = {c: x / 100 for c, x in zip(cols, row)}
        rec['Mom'] = m[0] / 100
        out[d] = rec
    FACT[region] = out
    return out


def factor_alpha(r, region, a, z, spread=None):
    """切片（年率%）と NW t。spread を渡すと r − spread（買いと買いの差＝自己資金のいらない形）を回帰する（E9）"""
    F = factors(region)
    ks = [k for k in sorted(r) if a <= k <= z and k in F and (spread is None or k in spread)]
    if len(ks) < 36:
        return None
    names = ['Mkt-RF', 'SMB', 'HML', 'RMW', 'CMA', 'Mom']
    y = [r[k] - (spread[k] if spread is not None else F[k]['RF']) for k in ks]
    X = [[1.0] + [F[k][c] for c in names] for k in ks]
    b, se, r2 = ols_nw(y, X)
    return {'region': region, 'from': ks[0], 'to': ks[-1], 'months': len(ks), 'alpha_ann': round(float(b[0]) * 1200, 2),
            't_alpha_nw12': round(float(b[0] / se[0]), 2), 'loadings': {c: round(float(x), 3) for c, x in zip(names, b[1:])},
            't_loadings': {c: round(float(x / s), 2) for c, x, s in zip(names, b[1:], se[1:])}, 'r2': round(float(r2), 3)}


def coverage(o, show=True):
    """被覆（成績は計算しない）: 形成ごとに ok / 値の無い上場会社 / 上場前の疑い（系列の始まり > 買う月）/ 非上場"""
    F = all_forms(o)
    late, miss = {}, {}
    rep = {}
    for name, fs in F.items():
        rows = []
        for f in fs:
            c = {'ok': 0, 'missing': 0, 'private': 0, 'pre_ipo': 0}
            for key, h in f['hold'].items():
                st, tk = resolve(key, h, f['buy'])
                c[st] += 1
                if st == 'missing':
                    starts = [(tk2, usd_returns(tk2)['first']) for tk2 in h['cands'] if usd_returns(tk2)]
                    if starts and all(a > f['buy'] for _, a in starts):
                        late.setdefault((name.startswith('E12') and 'FORBES' or f['list'], key), []).append((f['list_year'], f['buy'], starts))
                    else:
                        miss.setdefault((f['list'], key), []).append((f['list_year'], h['label'], h['cands'], [
                            (tk2, usd_returns(tk2) and (usd_returns(tk2)['first'], usd_returns(tk2)['last'])) for tk2 in h['cands']]))
            rows.append((f['list_year'], f['buy'], c))
        rep[name] = rows
    if show:
        for name, rows in rep.items():
            print(name, [(y, c['ok'], c['missing'], c['private'], c['pre_ipo']) for y, M, c in rows])
        print('== 系列の始まりが買う月より後（上場前か、データの始まりが遅いだけか）')
        for k, v in sorted(late.items(), key=str):
            print(k, v)
        print('== 値の無い上場会社（候補の記号が無い・404・買う月に値なし）')
        for k, v in sorted(miss.items(), key=str):
            print(k, v[0][1], v[0][2], v[0][3], [x[0] for x in v])
    return rep, late, miss



# ───────────────────────── 事前登録から外れたところ（測る前の記号の訂正など・結果を見て変えたものではない） ─────────────────────────
DEVIATIONS = []


def apply_fixes(o):
    """記号の誤り・消えた記号の訂正（成績を計算する前に、被覆の表示だけを見て決めた）"""
    P = o['parents']
    if 'TMPV.NS' not in P['TATAMOTORS']['yahoo']:
        P['TATAMOTORS']['yahoo'] = list(P['TATAMOTORS']['yahoo']) + ['TMPV.NS']
    DEVIATIONS.append({'what': 'Interbrand の親会社 TATAMOTORS（Tata Motors）の記号の候補の末尾に TMPV.NS を足した',
                       'why': "対応表の候補 TATAMOTORS.NS・TTM は Yahoo で 404（2025-10 の分割で Tata Motors Ltd が Tata Motors Passenger Vehicles Ltd に改名し記号が変わった・TTM の ADR は 2023 に上場廃止）。"
                              "TMPV.NS は同じ上場会社で 1991 年からの履歴がある（Yahoo の meta: 'Tata Motors Passenger Vehicles Limited'・firstTradeDate 1991-01-02）。全体版（P3・E4）の1社",
                       'affects_grade': '全体版の1社の値の有無だけ（base では値の無い会社として外れる代わりに持つ）'})
    n = 0
    for y, v in o['wmac'].items():
        for r in v['rows']:
            if r.get('yahoo') == 'BFB':
                r['yahoo'] = 'BF-B'
                n += 1
    DEVIATIONS.append({'what': f'WMAC の Brown-Forman の記号 BFB を BF-B に直した（{n} 行）',
                       'why': 'Fortune の会社ページの記号 BF.B の点が落ちた形で、Yahoo に BFB は無い（404）。BF-B が Brown-Forman の B 株',
                       'affects_grade': 'E8・E10・E11 の候補の1社（主の族には入らない）'})
    PRE_IPO['/company/levi-strauss/'] = 201903
    DEVIATIONS.append({'what': 'WMAC の Levi Strauss（2014・2015 の候補）を上場前として母集団から外した',
                       'why': 'Yahoo の LEVI は 2019-03-21 の上場から。当時は株が上場していない（非上場と同じ＝買えない）。事前登録の missing_rules.private と同じ扱い',
                       'affects_grade': 'E8 の下限版・中立版だけ（base では元から値が無いので外れる）'})
    DEVIATIONS.append({'what': 'WMAC の候補のうち一度も株が上場していない会社（相互会社・協同組合・パートナーシップ・従業員所有: USAA・State Farm・Northwestern Mutual・New York Life・MassMutual・Nationwide・Liberty Mutual・TIAA・Thrivent・Publix・Graybar・Peter Kiewit・Jones Financial・Land O\'Lakes・CH2M Hill）を非上場として母集団から外した',
                       'why': '事前登録の missing_rules.private（非上場は買えないので母集団から外す）を WMAC に当てる形を、事前登録は名前で決めていなかった。Fortune の Company type は今の種類（買収された会社も Private）なので使えず、名前で固定した',
                       'affects_grade': 'P4・E6〜E11 の下限版・中立版（base は元から値が無いので外れる）。All-Stars では Publix・USAA'})


# ───────────────────────── 分離（spin-off）の検査 ─────────────────────────
SPIN_RATIO = {  # Yahoo が反映していないと確かめた分離の、一次の出所で確かめた比率（受け取る株数 / 親の1株）と受け取った株の価値
    ('TATAMOTORS', 202510): {'ratio': 1.0, 'ex_date': '2025-10-14',
                             'source': 'Tata Motors Ltd の BSE/NSE への通知（2025-09-26・Sc no. 18755）: 『1 (one) fully paid equity share in TMLCV (face value of ₹2/- each) for every 1 (one) fully paid equity share of the Company』'
                                       ' https://static-assets.tatamotors.com/Production/www-tatamotors-com-NEW/wp-content/uploads/2025/09/NSEBSEORDER-270925-3.pdf'},
}


def _daily(tk):
    j = yh_json(tk, '1d', fetch=True)
    if not j or not (j.get('chart') or {}).get('result'):
        return None
    r = j['chart']['result'][0]
    q = r['indicators']['quote'][0]
    ad = (r['indicators'].get('adjclose') or [{}])[0].get('adjclose') or q['close']
    rows = []
    off = int((r.get('meta') or {}).get('gmtoffset') or 0)
    for i, t in enumerate(r.get('timestamp') or []):
        c, a = q['close'][i], ad[i]
        if c is None or a is None:
            continue
        # 日足の時刻は取引所の寄り付き（ニューヨークは UTC 13:30）。月足と同じ +12 時間では米国の日付が1日先へずれるので、現地の時刻で日付を読む
        d = datetime.datetime.utcfromtimestamp(t + off).date()
        rows.append({'d': d.isoformat(), 'ym': d.year * 100 + d.month, 'open': q['open'][i], 'close': c, 'adj': a})
    return {'rows': rows, 'events': r.get('events') or {}}


def spin_check(o):
    P = o['parents']
    out = []
    for pid, ym, desc in o['events']:
        rec = {'parent': pid, 'month': ym, 'what': desc}
        tk = None
        for c in (P.get(pid) or {}).get('yahoo') or []:
            u = usd_returns(c)
            if u and u['first'] < ym <= u['last']:
                tk = c
                break
        if not tk:
            rec.update(verdict='系列なし（値の無い親会社として missing の約束に回る）', ticker=None)
            out.append(rec)
            continue
        dd = _daily(tk)
        lo, hi = ym_prev(ym), ym_next(ym)
        win, prev = [], None
        for r in dd['rows']:
            if prev and lo <= r['ym'] <= hi:
                win.append((r['d'], r['close'] / prev['close'] - 1, r['adj'] / prev['adj'] - 1, prev, r))
            prev = r
        wc = min(win, key=lambda x: x[1])
        wa = min(win, key=lambda x: x[2])
        big_div = []
        for k, v in (dd['events'].get('dividends') or {}).items():
            d = datetime.datetime.utcfromtimestamp(int(k) + 43200).date()
            yy = d.year * 100 + d.month
            if lo <= yy <= hi:
                px = next((r['close'] for r in reversed(dd['rows']) if r['d'] < d.isoformat()), None)
                if px and v.get('amount', 0) > 0.05 * px:
                    big_div.append((d.isoformat(), round(v['amount'], 3), round(v['amount'] / px, 3)))
        rec.update(ticker=tk, worst_close_day=(wc[0], round(wc[1], 4), round(wc[2], 4)), worst_adj_day=(wa[0], round(wa[2], 4)),
                   large_dividend_adjustments=big_div, month_return_usd=round(usd_returns(tk)['r'].get(ym, float('nan')), 4))
        if 'Kenvue' in desc:
            rec['verdict'] = '交換買付（応じなければ株価に分離の段差は出ない）＝手直し不要'
        elif wa[2] > -0.15:
            rec['verdict'] = ('反映済み: 調整後終値の日々の下落に分離の段差が無い'
                              + ('（Yahoo が分離を大きな配当として調整後終値に入れている）' if big_div else '（Yahoo が分離より前の履歴を分割と同じ形で書き直している＝終値も連続）'))
        else:
            fx = SPIN_RATIO.get((pid, ym))
            if not fx:
                rec['verdict'] = '反映されていない・比率が一次の出所で確かめられない → その月を値の無い月として扱う'
                BAD_MONTH.setdefault(tk, set()).add(ym)
            else:
                pre = wa[3]
                exd = wa[4]
                v0 = pre['close'] - exd['open'] * 1.0
                s = series(tk)
                c_prev, c_now = s['close'][ym_prev(ym)], s['close'][ym]
                r_loc = (c_now + fx['ratio'] * v0) / c_prev - 1
                u = usd_returns(tk)
                if u.get('fx'):
                    f = fx_series(s['ccy'])['fx']
                    r_usd = (1 + r_loc) * f[ym] / f[ym_prev(ym)] - 1
                else:
                    r_usd = r_loc
                SPIN_FIX.setdefault(tk, {})[ym] = r_usd
                rec['verdict'] = (f"反映されていない（{wa[0]} に調整後終値も {round(wa[2] * 100, 1)}%）→ 一次の出所で比率 {fx['ratio']} を確かめ、"
                                  f"受け取った株の価値＝分離の前日の終値 {round(pre['close'], 2)} − 分離の日の寄り付き（取引所の値決め）{round(exd['open'], 2)} = {round(v0, 2)} で、"
                                  f"その月のリターンを {round(u['r'][ym] * 100, 2)}% → {round(r_usd * 100, 2)}%（ドル）に置き換えた")
                rec['source'] = fx['source']
                DEVIATIONS.append({'what': f'{pid} {ym} の分離: 受け取った株（TMCV）は {ym} の月末にまだ上場していない（2025-11-12 上場）ので、月末の値の代わりに分離の日の取引所の値決めから出した価値を使い、{ym} の月末の買い直しで売ったものとした',
                                   'why': '事前登録は『受け取った株は翌月末に売って親会社に戻す』だが、月末の値が無く、同じ月末に一覧の買い直し（2025 の一覧）がある。最も近い形',
                                   'affects_grade': '全体版（P3・E4）の1社の1か月だけ'})
        out.append(rec)
    return out


# ───────────────────────── 外れ値の月（+100% 超・−60% 未満）の検査 ─────────────────────────
def held_pairs(forms_list):
    pairs = {}
    for fs in forms_list:
        for f in fs:
            M, H = f['buy'], min(f['last'], END)
            for key, h in f['hold'].items():
                st, tk = resolve(key, h, M)
                if st != 'ok':
                    continue
                for t in ym_range(ym_next(M), H):
                    x = ret_of(tk, t)
                    if x is not None:
                        pairs[(tk, t)] = (x, h['label'])
    return pairs


def outlier_check(pairs, bench):
    out, diag = [], []
    for (tk, t), (x, label) in sorted(pairs.items()):
        if tk.startswith('AV:'):
            continue
        if x > 1.0 or x < -0.6:
            dd = _daily(tk)
            s = series(tk)
            u = usd_returns(tk)
            prevm = max(k for k in u['px_months'] if k < t)
            a0 = [r for r in dd['rows'] if r['ym'] == prevm]
            a1 = [r for r in dd['rows'] if r['ym'] == t]
            rd = (a1[-1]['adj'] / a0[-1]['adj'] - 1) if (a0 and a1) else None
            if rd is not None and u.get('fx'):
                f = fx_series(s['ccy'])['fx']
                rd = (1 + rd) * f[t] / f[prevm] - 1
            err = rd is not None and abs(rd - x) > 0.10
            if err:
                BAD_MONTH.setdefault(tk, set()).add(t)
            out.append({'ticker': tk, 'name': label, 'month': t, 'monthly': round(x, 4), 'daily_compound': rd if rd is None else round(rd, 4),
                        'verdict': 'データの誤り（月足と日足が 10% 超ずれる）→ 値の無い月として扱う' if err else ('日足と一致＝本物の動き' if rd is not None else '日足が無く確かめられない＝そのまま')})
        b = bench.get(t)
        if x < -0.25 and b is not None and b > -0.10:
            diag.append((tk, label, t, round(x, 4), round(b, 4)))
    return out, diag


# ───────────────────────── 規則ごとの測定 ─────────────────────────
def window_of(forms):
    return ym_next(forms[0]['buy']), min(max(f['last'] for f in forms), END)


def stats_block(r, b, a, z, rf):
    full = N.excess_stats(r, b, a, z)
    (a1, z1), (a2, z2) = halves(r, a, z)
    return full, N.excess_stats(r, b, a1, z1), N.excess_stats(r, b, a2, z2), ((a1, z1), (a2, z2))


def measure(rid, family, desc, forms, bench, bench_name, weights, cost_key, rf, alpha_region, bench_is_rule=None):
    a, z = window_of(forms)
    base = simulate(forms, bench, 'base', weights)
    r = base['r']
    b = bench
    full, h1, h2, hw = stats_block(r, b, a, z, rf)
    top = max(base['contrib'], key=lambda k: base['contrib'][k])
    dt = simulate(forms, bench, 'base', weights, exclude=frozenset([top]))
    drop_top = N.excess_stats(dt['r'], b, a, z)
    ann_to = annual_turnover(base, a, z)
    net = N.apply_cost(r, ann_to, COST[cost_key])
    cost_full = N.excess_stats(net, b, a, z)
    net_s = N.apply_cost(r, ann_to, COST_SENS[cost_key])
    lo = simulate(forms, bench, 'lower', weights)
    lower = N.excess_stats(lo['r'], b, a, z)
    ne = simulate(forms, bench, 'neutral', weights)
    neutral = N.excess_stats(ne['r'], b, a, z)
    rr = {k: v for k, v in r.items() if a <= k <= z}
    bb = {k: v for k, v in b.items() if a <= k <= z}
    top_c = sorted(base['contrib'].items(), key=lambda kv: -kv[1])
    rec = {
        'id': rid, 'family': family, 'desc': desc, 'benchmark': bench_name, 'weights': weights, 'window': [a, z], 'months': len(rr),
        'halves_windows': hw,
        'full': full, 'first_half': h1, 'second_half': h2,
        'train': None, 'train_note': 'この一覧のデータは 2007 年（Interbrand）・2014 年（WMAC）・2012 年（Forbes）からで 2006 年以前の訓練期間が無い（短い標本の格付け）',
        'hold_2007on': N.excess_stats(r, b, max(a, N.HOLD_START), z),
        'recent_2013_07on': N.excess_stats(r, b, max(a, N.RECENT_START), z),
        'cost': {'annual_oneway_turnover': round(ann_to, 3), 'cost_per_unit': COST[cost_key], 'after_cost_full': cost_full,
                 'sensitivity_cost_per_unit': COST_SENS[cost_key], 'after_cost_sensitivity_full': N.excess_stats(net_s, b, a, z)},
        'drop_top': {'dropped': top, 'dropped_label': str(top), 'contrib_ann_pct': round(base['contrib'][top] / (len(rr) / 12) * 100, 3), 'stats': drop_top,
                     'top5_contrib': [(str(k), round(v / (len(rr) / 12) * 100, 3)) for k, v in top_c[:5]],
                     'bottom5_contrib': [(str(k), round(v / (len(rr) / 12) * 100, 3)) for k, v in top_c[-5:]]},
        'lower_bound': lower, 'neutral_R5': neutral,
        'roll20': N.rolling(rr, bb, 20), 'roll10_report': N.rolling(rr, bb, 10), 'roll5_report': N.rolling(rr, bb, 5),
        'dca20_ratio': N.dca(rr, bb, 20), 'dca10_ratio_report': N.dca(rr, bb, 10, step=12),
        'roll20_dca20_note': '評価の期間が 20 年に満たない（Interbrand 19.0 年・WMAC 12.3 年・Forbes 6.7 年）ので 20 年窓・20 年積立は None。10 年・5 年は報告のみ',
        'maxdd': {'rule': round(N.maxdd(rr) * 100, 1), 'bench': round(N.maxdd(bb) * 100, 1)},
        'sharpe': {'rule': N.sharpe(rr, rf), 'bench': N.sharpe(bb, rf), 'note': '重ねる・借入・時期選びの型ではない＝C8 は該当なし（報告のみ）'},
        'by_list_year_R8': by_year(base, b),
        'factor_alpha_R4': (factor_alpha(rr, alpha_region, a, z, spread=bb) if bench_is_rule else factor_alpha(rr, alpha_region, a, z)) if alpha_region else None,
        'forms': base['forms'],
    }
    if bench_is_rule:
        rec['bench_note'] = bench_is_rule
    return rec, base


def grade_rec(rec, holm_p):
    g, c = N.grade_short(rec['full'], rec['first_half'], rec['second_half'], rec['drop_top']['stats'], rec['cost']['after_cost_full'],
                         rec['lower_bound'], holm_p)
    rec['grade'] = g
    rec['criteria_short'] = c
    rec['holm_p_one'] = holm_p
    # 参考: 長い歴史の線（C1〜C8）。訓練期間が無いので C1 は構造的に不合格（事前登録の格付けではない）
    gl, cl = N.grade(rec['full'], None, rec['hold_2007on'], rec['roll20'], rec['cost']['after_cost_full'], None,
                     None, None, False)
    rec['criteria_long_reference'] = {'grade_if_long_history_rules': gl, 'C': cl,
                                      'note': '参考のみ。事前登録は criteria_short_sample（grade_short）を決めた。訓練期間（〜2006）が無く C1 は構造的に不合格、20年窓も取れない'}
    return rec


# ───────────────────────── 事後の診断（結果を見た後に足した・格付けに使わない） ─────────────────────────
TECH6 = ('AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA')


def _ok_vals(f):
    out = {}
    for k, h in f['hold'].items():
        st, tk = resolve(k, h, f['buy'])
        if st == 'ok':
            out[k] = h['val']
    return out


def _clone(f, hold):
    return dict(f, hold=hold)


def _spy_hold(v):
    return {'cands': ['SPY'], 'status': 'listed', 'val': v, 'grid_val': 0.0, 'rows': [], 'label': 'SPY', 'old': None}


def post_hoc(F, spy, sims, recs):
    out = {'note': '★すべて事後（結果を見た後に足した診断）。格付けには使わない'}
    a, z = recs['P2_IB_US_BVW']['window']
    # PH1: P2 の巨大テック6社の重みをそのまま持ち、残りを SPY で持った『まね』＝巨大テックへの集中で説明できる分
    mim, ex6, cap10 = [], [], []
    for f in F['P1']:
        ov = _ok_vals(f)
        tech = {k: f['hold'][k] for k in ov if k in TECH6}
        rest = sum(v for k, v in ov.items() if k not in TECH6)
        mim.append(_clone(f, dict(tech, SPYMIMIC=_spy_hold(rest))))
        ex6.append(_clone(f, {k: v for k, v in f['hold'].items() if k not in TECH6}))
        tot = sum(ov.values())
        w = {k: v / tot for k, v in ov.items()}
        for _ in range(50):
            over = {k: x for k, x in w.items() if x > 0.10 + 1e-12}
            if not over:
                break
            excess = sum(x - 0.10 for x in over.values())
            under = {k: x for k, x in w.items() if x < 0.10}
            su = sum(under.values())
            w = {k: (0.10 if k in over else x + excess * x / su) for k, x in w.items()}
        cap10.append(_clone(f, {k: dict(f['hold'][k], val=w[k]) for k in w}))
    sm = simulate(mim, spy, 'base', 'bvw')
    s6 = simulate(ex6, spy, 'base', 'bvw')
    s6e = simulate([_clone(f, {k: v for k, v in f['hold'].items() if k not in TECH6}) for f in F['P1']], spy, 'base', 'ew')
    sc = simulate(cap10, spy, 'base', 'bvw')
    p2 = sims['P2_IB_US_BVW']['r']
    tw = []
    for f in F['P1']:
        ov = _ok_vals(f)
        tot = sum(ov.values())
        tw.append((f['list_year'], round(sum(v for k, v in ov.items() if k in TECH6) / tot * 100, 1)))
    out['PH1_P2_vs_tech6_mimic'] = {
        'desc': 'P2 の巨大テック6社（AAPL・MSFT・GOOGL・AMZN・META・NVDA）を P2 と同じ重みで持ち、残りの重みを SPY で持った『まね』と比べる。'
                'P2 − まね ＝ 巨大テック以外のブランドの選び方の効き、まね − SPY ＝ 巨大テックへの集中の効き',
        'tech6_weight_by_list_year_pct': tw,
        'mimic_minus_SPY': N.excess_stats(sm['r'], spy, a, z), 'P2_minus_mimic': N.excess_stats(p2, sm['r'], a, z)}
    out['PH2_P2_ex_tech6'] = {'desc': 'P2 から巨大テック6社をすべての年で外した版（残りで重みを割り直す）', 'vs_SPY': N.excess_stats(s6['r'], spy, a, z)}
    out['PH3_P1_ex_tech6'] = {'desc': 'P1（等分）から巨大テック6社を外した版', 'vs_SPY': N.excess_stats(s6e['r'], spy, a, z)}
    out['PH4_P2_cap10'] = {'desc': 'P2 の1社の重みを買う月に 10% までに抑えた版（あふれた分は残りへ比例で配る）', 'vs_SPY': N.excess_stats(sc['r'], spy, a, z)}
    out['PH5_P2_minus_P1'] = {'desc': 'ブランド価値の加重 − 等分（同じ一覧・同じ母集団）', 'stats': N.excess_stats(p2, sims['P1_IB_US_EW']['r'], a, z)}
    yrs = {}
    for rid in ('P1_IB_US_EW', 'P2_IB_US_BVW', 'P3_IB_GL_EW', 'P4_WMAC_US_EW', 'E4_IB_GL_BVW'):
        by = recs[rid]['by_list_year_R8']
        yrs[rid] = {'list_years': len(by), 'positive': sum(1 for x in by if x['diff'] > 0), 'diffs': [(x['list_year'], x['diff']) for x in by]}
    out['PH6_list_year_hit_rate'] = yrs
    # PH7: 暦年の超過（年ごとの勝ち負けの並び）
    cal = {}
    for rid in ('P1_IB_US_EW', 'P2_IB_US_BVW', 'P3_IB_GL_EW', 'E4_IB_GL_BVW'):
        r = sims[rid]['r']
        b = spy if recs[rid]['benchmark'] == 'SPY' else None
        if b is None:
            continue
        row = []
        for y in range(2008, 2026):
            ks = [k for k in r if k // 100 == y and k in b]
            if len(ks) == 12:
                row.append((y, round((math.prod(1 + r[k] for k in ks) - math.prod(1 + b[k] for k in ks)) * 100, 2)))
        cal[rid] = row
    out['PH7_calendar_year_excess_vs_SPY'] = cal
    return out


def run():
    pre, o, sha = load_lists()
    apply_fixes(o)
    # 先読みの検査・期間の重なりと隙間の検査
    sched = [x for x in o['interbrand']['schedule'] if x['used']]
    for x in sched:
        yr = o['interbrand']['years'][x['list_year']]
        if yr.get('release_date'):
            assert x['buy_month'] >= B.purchase_month(yr['release_date']), x
        else:
            mm = re.search(r'D:(\d{4})(\d{2})', yr['pdf']['created'])
            assert x['buy_month'] > int(mm.group(1)) * 100 + int(mm.group(2)), x
    for a_, b_ in zip(sched, sched[1:]):
        assert a_['hold_last_month'] == b_['buy_month']
    wy = sorted(o['wmac'])
    for y in wy:
        assert o['wmac'][y]['buy_month'] >= B.purchase_month(o['wmac'][y]['published_gmt'])
    for a_, b_ in zip(wy, wy[1:]):
        assert o['wmac'][a_]['hold_last_month'] == o['wmac'][b_]['buy_month']
    fy = [y for y in sorted(o['forbes']) if o['forbes'][y]['usable']]
    for y in fy:
        assert o['forbes'][y]['buy_month'] >= B.purchase_month(o['forbes'][y]['published'])
    for a_, b_ in zip(fy, fy[1:]):
        assert o['forbes'][a_]['hold_last_month'] == o['forbes'][b_]['buy_month']

    for c in ('CAD', 'CHF', 'DKK', 'EUR', 'GBp', 'HKD', 'INR', 'JPY', 'KRW', 'SEK', 'TWD'):
        fx_series(c)
    spy = usd_returns('SPY')['r']
    dev3 = next(v for k, v in N.french_tables('Developed_3_Factors').items() if v['freq'] == 'monthly')
    dev = {d: (row[0] + row[3]) / 100 for d, row in dev3['data'].items() if row[0] is not None and row[3] is not None}
    dx3 = next(v for k, v in N.french_tables('Developed_ex_US_3_Factors').items() if v['freq'] == 'monthly')
    devx = {d: (row[0] + row[3]) / 100 for d, row in dx3['data'].items() if row[0] is not None and row[3] is not None}
    ff = N.ff_factors()
    rf, mkt = ff['rf'], ff['mkt']

    spins = spin_check(o)
    F = all_forms(o)
    F['P2'] = F['P1']
    F['E4'] = F['P3']
    pairs = held_pairs([F[k] for k in ('P1', 'P3', 'P4', 'E1', 'E2', 'E3', 'E5', 'E6', 'E7', 'E8', 'E10', 'E11', 'E12', 'R1', 'R2', 'NONUS')])
    outl, diag = outlier_check(pairs, spy)

    spec = [
        ('P1_IB_US_EW', 'primary', 'Interbrand 17年分（当時の原本）の米国の親会社を等分・相手 SPY', 'P1', spy, 'SPY', 'ew', 'us', 'us'),
        ('P2_IB_US_BVW', 'primary', '同じ一覧の米国の親会社をブランド価値で加重・相手 SPY', 'P2', spy, 'SPY', 'bvw', 'us', 'us'),
        ('P3_IB_GL_EW', 'primary', '同じ一覧の上場している親会社すべて（米国外はドル建て）を等分・相手 French Developed', 'P3', dev, 'French Developed Mkt', 'ew', 'global', 'dev'),
        ('P4_WMAC_US_EW', 'primary', 'Fortune WMAC の All-Stars（米国）を等分・相手 SPY', 'P4', spy, 'SPY', 'ew', 'us', 'us'),
        ('E1_IB_US_EW_top50', 'exploratory', 'P1 を順位 1〜50 のブランドの親会社だけで', 'E1', spy, 'SPY', 'ew', 'us', 'us'),
        ('E2_IB_US_EW_risers', 'exploratory', 'P1 の母集団のうちブランド価値の前年比が上位 1/3', 'E2', spy, 'SPY', 'ew', 'us', 'us'),
        ('E3_IB_US_EW_fallers', 'exploratory', 'P1 の母集団のうちブランド価値の前年比が下位 1/3', 'E3', spy, 'SPY', 'ew', 'us', 'us'),
        ('E4_IB_GL_BVW', 'exploratory', 'P3 をブランド価値の加重で・相手 French Developed', 'E4', dev, 'French Developed Mkt', 'bvw', 'global', 'dev'),
        ('E5_IB_US_EW_uniform_nov', 'exploratory', 'P1 をどの年も11月末に買い直す形で', 'E5', spy, 'SPY', 'ew', 'us', 'us'),
        ('E6_WMAC_US_top10', 'exploratory', 'P4 を All-Star 順位 1〜10 だけで', 'E6', spy, 'SPY', 'ew', 'us', 'us'),
        ('E7_WMAC_GL_EW', 'exploratory', 'P4 を全体版で（米国外は Fortune の記号＝多くは ADR・OTC）・相手 French Developed', 'E7', dev, 'French Developed Mkt', 'ew', 'global', 'dev'),
        ('E8_WMAC_US_contenders', 'exploratory', 'WMAC の候補のうち All-Stars でない米国の会社を等分・相手 SPY', 'E8', spy, 'SPY', 'ew', 'us', 'us'),
        ('E10_WMAC_US_industry_leaders', 'exploratory', '業種内順位 1位の米国の会社を等分・相手 SPY（2016〜）', 'E10', spy, 'SPY', 'ew', 'us', 'us'),
        ('E11_WMAC_US_industry_laggards', 'exploratory', '業種内順位がその業種の最下位の米国の会社を等分・相手 SPY（2016〜）', 'E11', spy, 'SPY', 'ew', 'us', 'us'),
        ('E12_FORBES_US_EW', 'exploratory', 'Forbes の一覧の米国の会社を等分・相手 SPY（2012-10〜2019-05）', 'E12', spy, 'SPY', 'ew', 'us', 'us'),
    ]
    recs, sims = {}, {}
    for rid, fam, desc, fk, bench, bname, w, ck, reg in spec:
        rec, base = measure(rid, fam, desc, F[fk], bench, bname, w, ck, rf, reg)
        recs[rid], sims[rid] = rec, base
        print(rid, rec['full'] and (rec['full']['cagr_diff'], rec['full']['t']), flush=True)
    # E9: P4 の All-Stars を、同じ投票の候補（E8）の等分と比べる
    e8 = sims['E8_WMAC_US_contenders']['r']
    rec, base = measure('E9_WMAC_US_allstars_vs_contenders', 'exploratory', 'P4 の All-Stars（米国）を E8 の候補の等分と比べる', F['P4'], e8,
                        'E8（候補の等分・base）', 'ew', 'us', rf, 'us',
                        bench_is_rule='相手は E8 の base 版（値の無い会社を外した等分・費用前）。下限版・費用後は規則の側だけに掛ける（保守的）')
    recs[rec['id']], sims[rec['id']] = rec, base
    print(rec['id'], rec['full'] and (rec['full']['cagr_diff'], rec['full']['t']), flush=True)

    prim = {k: N.p_one(v['full']['t']) if v['full'] else None for k, v in recs.items() if v['family'] == 'primary'}
    expl = {k: N.p_one(v['full']['t']) if v['full'] else None for k, v in recs.items() if v['family'] == 'exploratory'}
    hp, he = N.holm(prim), N.holm(expl)
    for k, v in recs.items():
        grade_rec(v, (hp if v['family'] == 'primary' else he).get(k))

    # ── 報告のみ（格付けしない）
    rep = {}
    a1, z1 = window_of(F['R1'])
    r1 = simulate(F['R1'], spy, 'base', 'ew')
    rep['R1_hindsight_api'] = {'desc': 'P1 を Interbrand の API の生き残りの一覧（2007〜2019 は抜けた一覧・2015/2017 は10月に買う）で組んだ版（後知恵）',
                               'full': N.excess_stats(r1['r'], spy, a1, z1), 'vs_P1_same_window_cagr_diff':
                                   (N.excess_stats(r1['r'], sims['P1_IB_US_EW']['r'], a1, z1)), 'forms': r1['forms']}
    a2, z2 = window_of(F['R2'])
    r2 = simulate(F['R2'], spy, 'base', 'ew')
    rep['R2_hindsight_2001_2006'] = {'desc': '2001〜2006 の一覧を API の生き残りだけで組み（10月に買う）2001-11〜2007-08 を SPY と比べた（後知恵）',
                                     'full': N.excess_stats(r2['r'], spy, a2, z2), 'forms': r2['forms']}
    others = {}
    etf = {t: usd_returns(t)['r'] for t in ('OEF', 'RSP', 'MGC', 'QQQ', 'IOO', 'ACWI', 'MOAT')}
    for rid in ('P1_IB_US_EW', 'P2_IB_US_BVW', 'P4_WMAC_US_EW'):
        a, z = recs[rid]['window']
        rr = sims[rid]['r']
        others[rid] = {nm: N.excess_stats(rr, bm, a, z) for nm, bm in (('OEF', etf['OEF']), ('RSP', etf['RSP']), ('MGC', etf['MGC']),
                                                                        ('QQQ', etf['QQQ']), ('French_Mkt', mkt), ('MOAT', etf['MOAT']))}
    for rid in ('P3_IB_GL_EW', 'E4_IB_GL_BVW', 'E7_WMAC_GL_EW'):
        a, z = recs[rid]['window']
        rr = sims[rid]['r']
        others[rid] = {nm: N.excess_stats(rr, bm, a, z) for nm, bm in (('IOO', etf['IOO']), ('ACWI', etf['ACWI']), ('SPY', spy))}
    rep['R3_other_benchmarks'] = others
    rep['R4_factor_alpha'] = {k: v['factor_alpha_R4'] for k, v in recs.items()}
    rep['R5_neutral'] = {k: v['neutral_R5'] for k, v in recs.items()}
    r6 = {}
    for rid, fk, bench, w in (('P1_IB_US_EW', 'P1', spy, 'ew'), ('P2_IB_US_BVW', 'P2', spy, 'bvw'), ('P3_IB_GL_EW', 'P3', dev, 'ew'), ('E4_IB_GL_BVW', 'E4', dev, 'bvw')):
        a, z = recs[rid]['window']
        s6 = simulate(F[fk], bench, 'base', w, grid_bench=True)
        r6[rid] = N.excess_stats(s6['r'], bench, a, z)
    rep['R6_provenance_strict'] = r6
    rep['R7_cost_sensitivity'] = {k: v['cost']['after_cost_sensitivity_full'] for k, v in recs.items()}
    rep['R8_by_list_year'] = {k: v['by_list_year_R8'] for k, v in recs.items()}
    a, z = recs['P2_IB_US_BVW']['window']
    rep['R9_p2_vs_megacap'] = {'P2_minus_OEF': N.excess_stats(sims['P2_IB_US_BVW']['r'], etf['OEF'], a, z),
                               'P2_minus_MGC': N.excess_stats(sims['P2_IB_US_BVW']['r'], etf['MGC'], a, z)}
    # 3つの一覧・2つの地域で同じ向きに出るか（報告のみ・格付けに使わない）
    an, zn = window_of(F['NONUS'])
    nonus = simulate(F['NONUS'], devx, 'base', 'ew')
    rep['C5_like_units_report'] = {
        'Interbrand_US_vs_SPY(P1)': recs['P1_IB_US_EW']['full'],
        'Interbrand_nonUS_EW_vs_French_Developed_ex_US': N.excess_stats(nonus['r'], devx, an, zn),
        'Fortune_WMAC_US_vs_SPY(P4)': recs['P4_WMAC_US_EW']['full'],
        'Forbes_US_vs_SPY(E12)': recs['E12_FORBES_US_EW']['full'],
    }
    rep['C5_like_units_report']['same_sign_positive'] = sum(1 for v in rep['C5_like_units_report'].values() if isinstance(v, dict) and v and v['cagr_diff'] > 0)
    rep['C5_like_units_report']['units'] = 4

    ph = post_hoc(F, spy, sims, recs)
    tested = [recs[k] for k in recs]
    # 格付けしない報告（R1〜R9）と事後の診断も tested に1本ずつ残す（多重検定の数を数えるため・grade は None）
    def _t(i, fam, desc, st):
        return {'id': i, 'family': fam, 'desc': desc, 'grade': None, 'full': st}
    tested.append(_t('R1_hindsight_api', 'report_only', rep['R1_hindsight_api']['desc'], rep['R1_hindsight_api']['full']))
    tested.append(_t('R2_hindsight_2001_2006', 'report_only', rep['R2_hindsight_2001_2006']['desc'], rep['R2_hindsight_2001_2006']['full']))
    for rid, v in rep['R3_other_benchmarks'].items():
        for nm, st in v.items():
            tested.append(_t(f'R3_{rid}_vs_{nm}', 'report_only', f'{rid} を {nm} と比べた', st))
    for rid, st in rep['R6_provenance_strict'].items():
        tested.append(_t(f'R6_{rid}', 'report_only', f'{rid} の手がかり由来の名前の行を相手と同じリターンに', st))
    for nm, st in rep['R9_p2_vs_megacap'].items():
        tested.append(_t(f'R9_{nm}', 'report_only', nm, st))
    for nm, st in rep['C5_like_units_report'].items():
        if isinstance(st, dict):
            tested.append(_t(f'C5like_{nm}', 'report_only', '3つの一覧・2つの地域の並び（格付けに使わない）', st))
    tested.append(_t('PH1_mimic_minus_SPY', 'post_hoc', '事後: P2 の巨大テック6社の重み＋残りを SPY', ph['PH1_P2_vs_tech6_mimic']['mimic_minus_SPY']))
    tested.append(_t('PH1_P2_minus_mimic', 'post_hoc', '事後: P2 − 巨大テック6社のまね', ph['PH1_P2_vs_tech6_mimic']['P2_minus_mimic']))
    tested.append(_t('PH2_P2_ex_tech6', 'post_hoc', ph['PH2_P2_ex_tech6']['desc'], ph['PH2_P2_ex_tech6']['vs_SPY']))
    tested.append(_t('PH3_P1_ex_tech6', 'post_hoc', ph['PH3_P1_ex_tech6']['desc'], ph['PH3_P1_ex_tech6']['vs_SPY']))
    tested.append(_t('PH4_P2_cap10', 'post_hoc', ph['PH4_P2_cap10']['desc'], ph['PH4_P2_cap10']['vs_SPY']))
    tested.append(_t('PH5_P2_minus_P1', 'post_hoc', ph['PH5_P2_minus_P1']['desc'], ph['PH5_P2_minus_P1']['stats']))
    grades = {k: v['grade'] for k, v in recs.items()}
    best = max(recs.values(), key=lambda v: ({'S': 3, 'A': 2, 'B': 1, 'C': 0}[v['grade']] + (0.5 if v['family'] == 'primary' else 0), (v['full'] or {}).get('cagr_diff', -99)))
    out = {
        'angle': 'nx_brand', 'prereg': 'out/nx_brand_prereg.json', 'global_prereg': 'out/nx_prereg.json（criteria_short_sample）',
        'lists_sha256_verified': sha, 'lists_sha256_prereg': pre['tools']['lists_sha256'],
        'grade_function': 'nx_common.grade_short（事前登録 criteria.which = criteria_short_sample）',
        'period_end': END,
        'deviations_from_prereg': DEVIATIONS + [
            {'what': '上場廃止した米国の親会社の Alpha Vantage 月次調整後（delisted_fallback）は使えなかった',
             'why': 'Alpha Vantage の MCP が 2026-09-28 に『25 requests per day』の上限に達していた（並走の他セッションが使い切った）。鍵のファイルもリポジトリに無い。'
                    'av_returns() はキャッシュ out/_nx_cache/av_{記号}_monthly_adj.json があれば使う形で残した（今回は1件も無い）',
             'affects_grade': 'Interbrand の BKC・EK・HNZ・MER・TIF・VIAB・WWY・YHOO・LNKD と WMAC の WFM・STJ・JWN は、事前登録どおり missing の約束（base は外す・下限版は −30%・中立版は相手と同じ）に回った。'
                              '★Kellanova（K）は 2025-12 の Mars の買収で Yahoo から消え、事前登録の OLD_TICKER にも無い＝Interbrand 2007〜2024 のすべての年で値の無い親会社になった（base では外れ、下限版は毎年 −30%＝下限版は本来より厳しい）'},
            {'what': 'Yahoo の月足の時刻を 12 時間ずらして月を読んだ',
             'why': '月の足の時刻は取引所の現地の 1日 0時で、UTC のまま読むと米国外の系列（東京・欧州・ソウル）と為替の月が1か月前にずれる（為替は毎年10月が抜けていた）。nx_common.yahoo() は UTC のまま読むので、この角度では自前の series() を使った（キャッシュは同じファイル）',
             'affects_grade': '米国外の株と為替（P3・E4・E7）。米国の株（ニューヨークの 0時 = UTC 4〜5時）は変わらない'},
            {'what': '★1回目の実行（結果を見た）の後に、外れ値の月の検査の道具の誤りを直して2回目を正とした',
             'why': '日足の日付を月足と同じ『+12 時間』で読んでいたため、米国の日足（時刻は寄り付きの UTC 13:30）の日付が1日先へずれ、月末の日足が翌月の初日と取り違えられていた。'
                    'その結果、日足と月足の突き合わせで本物の大きな動き5件（AIG 2009-03 +138%・AIG 2009-08 +245%・Ford 2009-04 +127%・Intel 2026-04 +114%・Wayfair 2020-04 +132%）を『データの誤り』と判定し、'
                    'その月から現金（base）に回していた。日足を取引所の現地の時刻（meta.gmtoffset）で読むように直すと、月足の終値は月の最後の取引日の終値と MSFT・SPY・7203.T・SIE.DE で 236/236 か月一致し、5件とも日足と一致した（誤りは0件）。'
                    '事前登録の『データの誤りと確かめられたときだけ値の無い月として扱う』の意図どおりに直したが、結果を見た後の直しで、直した向きは成績を良くする側なので、1回目の数字をここに残す',
             'first_run_numbers': {'P1_IB_US_EW': ('A', 1.78, 1.73), 'P2_IB_US_BVW': ('S', 3.15, 2.51), 'P3_IB_GL_EW': ('S', 1.90, 2.14), 'P4_WMAC_US_EW': ('B', 0.34, 0.33),
                                   'E1': ('B', 1.04, 1.00), 'E2': ('B', 1.67, 0.93), 'E3': ('B', 1.83, 1.36), 'E4': ('S', 3.69, 3.44), 'E5': ('B', 1.70, 1.64), 'E6': ('A', 4.19, 2.14),
                                   'E7': ('A', 2.88, 2.31), 'E8': ('C', -0.68, -0.24), 'E9': ('B', 1.02, 0.45), 'E10': ('C', -0.05, 0.12), 'E11': ('C', -1.02, -0.09), 'E12': ('B', 3.37, 1.35),
                                   'format': '(格付け, 全期間の幾何の年率差 %, NW t)'},
             'affects_grade': '主の族の格付けは変わらない（P1 A・P2 S・P3 S・P4 B のまま）。探索の E3・E5 が B → A に上がった（Holm は通らない）。同じ直しで E9 の因子の切片を P4 そのものではなく P4 − E8 の差で回帰するよう直した'},
            {'what': '為替の月足の壊れた月を、同じ記号の日足から作った月末の値に置き換えた（KRW 7か月・TWD 3か月）',
             'why': 'KRWUSD=X の月足は 2015-02・2015-10・2016-01・2016-07・2017-09 に 8〜9（本来 0.0009 前後）、TWDUSD=X は 2014-12 に 0.27（本来 0.032）＝データの誤り。月足と日足の月末が 3% 超ずれる月だけ置き換えた',
             'affects_grade': '韓国・台湾の株（Samsung・Hyundai・Kia・LG・HTC）を持つ全体版'},
        ],
        'implementation_notes': [
            'E2/E3 の 1/3 は round(n/3)（n = 前年比が計算できた米国の親会社の数）。前年比は Interbrand の公表値、無ければ前年の完全な一覧（あれば）か API の前年の値から。NEW は除く。親会社の複数のブランドは価値で加重',
            'E11 の最下位は『その業種の一覧の中で業種内順位が最も大きい会社』（全ての国の中で）で、それが米国の会社なら持つ',
            'E9 の相手は E8 の base 版。下限版・費用後は規則の側だけに掛けた（保守的）',
            'データの抜け（系列がその月だけ無く後で戻る）はその月を 0% とし、戻った月に抜けた間の動きをまとめて受ける。系列が終わったら base は現金・下限版は −30%・中立版は相手',
            '買う月に値が無い理由が『上場前』のもの（Levi Strauss）と非上場（Interbrand の PRIVATE・WMAC の相互会社など）は、どの版でも母集団から外す',
            '費用は年あたりの片道の回転（最初の買いの 1 を含む回転の合計 ÷ 年数）× 片道の回転 100% あたりの費用を nx_common.apply_cost で月割りに引いた',
            'drop_top は base の寄与 Σ w_{t−1}(r−b) が最大の1社を、全ての年から外して重みを割り直した版',
        ],
        'data_checks': {
            'spin_offs': spins, 'outliers_over100_under60': outl,
            'big_drop_months_diagnostic': {'rule': '持っている月で −25% 未満・相手 SPY は −10% 超（分離の調整漏れを目で探すための一覧。何も変えていない）', 'rows': diag},
            'fx_fixes': {c: [x for x in FXC[c]['fixes'] if x[0] >= 200701] for c in FXC if FXC[c]['fixes']},
            'fx_tickers': {c: FXC[c]['tk'] for c in FXC},
            'av_fallback_notes': AV_NOTE,
            'gaps_in_held_series': sorted({(tk, g) for (tk, t) in pairs for g in (usd_returns(tk) or {}).get('gaps', []) if g[1] >= 200708} , key=str)[:200],
        },
        'holm': {'primary_p_one': prim, 'primary_holm': hp, 'exploratory_p_one': expl, 'exploratory_holm': he},
        'grades': grades,
        'best': {'id': best['id'], 'grade': best['grade'], 'full': best['full']},
        'tested': tested,
        'report_only': rep,
        'post_hoc_diagnostics': ph,
    }
    for t in out['tested']:
        if 'halves_windows' in t:
            t['halves_windows'] = [list(x) for x in t['halves_windows']]
    def _f(st):
        return f"年率差 {st['cagr_diff']}%・NW t {st['t']}" if st else 'なし'
    R = recs
    phd = ph['PH1_P2_vs_tech6_mimic']
    out['summary_ja'] = [
        f"主の族（Holm 片側）: P1 等分 {R['P1_IB_US_EW']['grade']}（{_f(R['P1_IB_US_EW']['full'])}・Holm p {hp.get('P1_IB_US_EW')}）／"
        f"P2 ブランド価値の加重 {R['P2_IB_US_BVW']['grade']}（{_f(R['P2_IB_US_BVW']['full'])}・Holm p {hp.get('P2_IB_US_BVW')}）／"
        f"P3 全体版の等分 vs French Developed {R['P3_IB_GL_EW']['grade']}（{_f(R['P3_IB_GL_EW']['full'])}・Holm p {hp.get('P3_IB_GL_EW')}）／"
        f"P4 Fortune WMAC All-Stars {R['P4_WMAC_US_EW']['grade']}（{_f(R['P4_WMAC_US_EW']['full'])}）",
        f"探索: " + '・'.join(f"{k.split('_')[0]} {v['grade']}" for k, v in R.items() if v['family'] == 'exploratory'),
        f"★事後の診断（格付けに使わない）: P2 の勝ちは巨大テック6社（AAPL・MSFT・GOOGL・AMZN・META・NVDA）への集中でほぼ説明できる——"
        f"同じ重みで6社を持ち残りを SPY で持ったまねが SPY に {_f(phd['mimic_minus_SPY'])}、P2 − まね は {_f(phd['P2_minus_mimic'])}、"
        f"6社を外した P2 は SPY に {_f(ph['PH2_P2_ex_tech6']['vs_SPY'])}。6社の重みは {phd['tech6_weight_by_list_year_pct'][0][1]}%（2007）→ {phd['tech6_weight_by_list_year_pct'][-1][1]}%（2025）",
        f"P2 は QQQ には {_f(rep['R3_other_benchmarks']['P2_IB_US_BVW']['QQQ'])}、P1 は QQQ に {_f(rep['R3_other_benchmarks']['P1_IB_US_EW']['QQQ'])}、"
        f"P3 は SPY に {_f(rep['R3_other_benchmarks']['P3_IB_GL_EW']['SPY'])}（相手を French Developed から SPY に替えると負け）",
        f"後知恵の偏り: 今の Interbrand の API の生き残りの一覧で組むと P1 の相当は SPY に {_f(rep['R1_hindsight_api']['full'])}（当時の原本の P1 より {rep['R1_hindsight_api']['vs_P1_same_window_cagr_diff']['cagr_diff']}%/年 良く見える）",
    ]
    p = N.save(OUT_NAME, out)
    print('saved', p)
    return out


if __name__ == '__main__':
    if '--fetch' in sys.argv:
        _pre, _o, _sha = load_lists()
        apply_fixes(_o)
        fetch(_o)
    elif '--coverage' in sys.argv:
        _pre, _o, _sha = load_lists()
        apply_fixes(_o)
        coverage(_o)
    else:
        run()
