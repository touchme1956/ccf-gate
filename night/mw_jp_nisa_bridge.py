#!/usr/bin/env python3
"""night/mw_jp_nisa_bridge.py — 『市場に勝てる歴史検証』(mw) の角度 jp_nisa_bridge（読むだけ・門の判定には不使用）

問い: 日本の中で検証済みの上乗せ（配当利回り・割安＋勢い・割安＋質＋勢い）を、この投資家（楽天・国内株の手数料0・
      新NISA 2人分・毎月積立・ETF 側は NASDAQ100 75 : SMH 25）が東証ETF・日本の投信で NISA の中に持てるか。
      持てるとして、ETF 側の 10/20/30% を日本の袖に替えたら、円の毎月積立（20年）は今の ETF 側より良かったか・良くなりそうか。
事前登録: out/mw_jp_nisa_bridge_prereg.json（線は out/mw_prereg.json）。出力: out/mw_jp_nisa_bridge.json
使い方: python3 night/mw_jp_nisa_bridge.py

族
  P1 主（格付け）: French Japan の大型の角（ME5）の割安＋勢い／割安＋質／割安＋質＋勢い（円・相手は French Japan Mkt）
  X1 探索（格付け）: ME4＋ME5 へ広げた版
  X2 再現（格付け）: JKP 日本 vw の配当・割安＋勢い・割安＋質＋勢い（mw_japan の S を円で）
  P2 報告: 実在の器（東証ETF・米国ETF・MSCI の要因指数・日本の投信）の成績と、紙の上乗せへの載り（capture）
  P3 報告: 投資家の単位の円の毎月積立（積立金だけで組み直す・NISA と課税の3つの置き方）
  B  報告: 損益分岐の上乗せ（窓ごと）と、日本 − 米国の市場の差の基礎率（JST 1886〜2020・French 1975〜）
  F  報告: 前向きの模擬（復元抽出）と前向きの登録の仕様（器は規則で選ぶ）
"""
import collections, csv, datetime, http.cookiejar, io, json, math, os, re, statistics as S, subprocess, sys, time, urllib.request, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M
import numpy as np

PRE_NAME = 'mw_jp_nisa_bridge_prereg.json'
OUT_NAME = 'mw_jp_nisa_bridge.json'
PRE = json.load(open(os.path.join(M.BASE, 'out', PRE_NAME)))
TODAY = datetime.date.today()
NOW_YM = TODAY.year * 100 + TODAY.month
JKP_END = 202512
FRESH = 202304
TAX = 0.20315
US_WH = 0.10
LOG = []
DEVIATIONS = [
    '【データの修正・第1回の実行の後】mw_common.yahoo は月足の時刻を UTC で月に切るので、東証銘柄（JST の月初 00:00＝前日 15:00 UTC）が1か月前の月に付き、'
    '途中の今月（2026-09）の足が 2026-08 として残っていた（照合: 1698.T の Yahoo と投信協会の基準価額の月次の相関 0.03・1577.T −0.02・1478.T −0.06）。'
    'この道具の中だけ meta.gmtoffset で現地時刻の月に直した（mw_common は編集していない＝他の角度の東証銘柄〔mw_japan の E5 など〕も同じずれを持つ。'
    'mw_japan の E5 は相手も東証銘柄なので上乗せの平均はほぼ保たれるが、最後の月が途中の値）。規則は変えていない。第1回の P2 の東証ETF の数字と載り（capture）は無効',
    '【データの修正・第1回の実行の後】信託報酬の取得で、検索語が複数の ETF に当たった5本（1489・1651・1494・2564・1399）が空欄になり、前向きの器の規則 (c) で自動的に外れていた。'
    '検索結果に出た正しい名前の ISIN に固定して取り直した（取り方の誤りの修正・規則は同じ）。第1回の選択（両方の誤りの下で）は 1698.T',
    'BE1 の『対 S&P500』の g* は、混ぜた側の 80% が NASDAQ100・SMH なので、ほぼその2本が S&P500 に勝った分を映す（日本の袖の評価には使えない）。登録どおり出すが読みは『今の側と並ぶ g*』で行う（事後の注記）',
    '前向きの模擬に S3（事後・格付けに使わない）を足した: 平均を『算術平均が同じ』ではなく『対数の成長率が同じ』にそろえる（S1/S2 は揺れの小さい側が自動的に有利になる置き方だったため）',
    'out/mw_forward_prereg.json と night/mw_forward.py は別の角度の持ち物なので書き換えていない。前向きの登録は forward_registration_request に仕様だけ置いた',
]


def log(*a):
    s = ' '.join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


def r2(x, n=2):
    return None if x is None else round(float(x), n)


def prev_ym(m):
    y, mo = divmod(m, 100)
    return (y - 1) * 100 + 12 if mo == 1 else m - 1


def add_months(m, k):
    y, mo = divmod(m, 100)
    t = y * 12 + (mo - 1) + k
    return (t // 12) * 100 + t % 12 + 1


def git_sha(path):
    try:
        return subprocess.run(['git', '-C', M.BASE, 'log', '-1', '--format=%H', '--', path], capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


def lim(r, a=None, z=None):
    return {k: v for k, v in r.items() if (a is None or k >= a) and (z is None or k <= z)}


# ───────────────────────── 取得: 為替・French・JKP・MSCI・投信・Yahoo ─────────────────────────
def fx_monthend():
    txt = M.get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXJPUS', name='fred_DEXJPUS.csv', max_age_days=30).decode()
    out = {}
    for line in txt.splitlines()[1:]:
        p = line.split(',')
        if len(p) < 2:
            continue
        try:
            v = float(p[1])
        except ValueError:
            continue  # 欠測（'.'）は飛ばす＝0 にしない
        out[int(p[0][:4]) * 100 + int(p[0][5:7])] = v  # 月の最後の営業日の値が残る
    return out


FX = None


def to_jpy(r):
    out = {}
    for m, v in r.items():
        p = prev_ym(m)
        if m in FX and p in FX:
            out[m] = (1 + v) * FX[m] / FX[p] - 1
    return out


def fr_vw(name):
    for t, v in M.french_tables(name).items():
        if v['freq'] == 'monthly' and 'value weight' in t.lower():
            return {c: {d: row[i] / 100 for d, row in v['data'].items() if row[i] is not None} for i, c in enumerate(v['cols'])}
    raise KeyError(name)


def fr_mkt(region):
    for t, v in M.french_tables(f'{region}_3_Factors').items():
        if v['freq'] == 'monthly' and 'Mkt-RF' in v['cols']:
            i, j = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
            return {d: (row[i] + row[j]) / 100 for d, row in v['data'].items() if row[i] is not None and row[j] is not None}
    raise KeyError(region)


FR_INTL_URL = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_International_Countries.zip'


def fr_intl_japan(cur='Local'):
    """French International Countries の Japan.Dat（Value-Weight・Not Reqd）の Mkt 列 → {ym: 小数}"""
    z = zipfile.ZipFile(io.BytesIO(M.get(FR_INTL_URL, name='fr_F-F_International_Countries.zip')))
    out, active = {}, False
    for line in z.read('Japan.Dat').decode('latin-1').splitlines():
        if 'Value-Weight' in line:
            active = (cur in line) and ('Not Reqd' in line)
            continue
        m = re.match(r'^\s*(\d{6})\s+(.*)$', line)
        if active and m:
            x = float(m.group(2).split()[0])
            if x <= -99.99 or x == -999:
                continue
            out[int(m.group(1))] = x / 100
    return out


def mix(legs, weights=None):
    """脚（{ym: r} の列）を毎月その比に組み直す。全部の脚がそろう月だけ"""
    ms = set(legs[0])
    for l in legs[1:]:
        ms &= set(l)
    w = weights or [1 / len(legs)] * len(legs)
    return {m: sum(wi * l[m] for wi, l in zip(w, legs)) for m in sorted(ms)}


RF = None


def jkp_all(loc):
    """JKP の all_factors 三分位（vw）→ {特性: {pf: {ym: (ret, n)}}}（超過・米ドル）"""
    out = collections.defaultdict(lambda: collections.defaultdict(dict))
    for x in M.jkp_rows(loc, 'all_factors', 'portfolios', 'vw'):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        n = int(float(x['n'])) if x['n'] not in ('', 'NA', 'na') else 0
        out[x['name']][x['pf']][M._ym(x['date'])] = (float(x['ret']), n)
    return out


def jkp_strat(pf, comps, nmin):
    """comps=[(特性, pf)] を等分。各脚の n≥nmin の月だけ・全部そろう月だけ（欠けを 0 と読まない）"""
    legs = []
    for k, side in comps:
        d = (pf.get(k) or {}).get(side) or {}
        legs.append({m: r for m, (r, n) in d.items() if n >= nmin})
    if not legs or any(not l for l in legs):
        return {}
    return mix(legs)


def tot_usd(ex):
    return {m: v + RF[m] for m, v in ex.items() if m in RF}


def last_month_end():
    d = TODAY.replace(day=1) - datetime.timedelta(days=1)
    return d.year * 10000 + d.month * 100 + d.day


def msci(code, variant='GRTR'):
    """MSCI の月末の水準（円）→ 月次リターン。API は 1997-01 より前を返さない"""
    url = (f'https://app2.msci.com/products/service/index/indexmaster/getLevelDataForGraph?currency_symbol=JPY&index_variant={variant}'
           f'&start_date=19970101&end_date={last_month_end()}&data_frequency=END_OF_MONTH&baseValue=false&index_codes={code}')
    j = json.loads(M.get(url, name=f'jnb_msci_{code}_{variant}_JPY.json', max_age_days=7))
    lv = {}
    for x in j['indexes']['INDEX_LEVELS']:
        lv[x['calc_date'] // 100] = x['level_eod']
    ks = sorted(lv)
    return {k: lv[k] / lv[p] - 1 for p, k in zip(ks, ks[1:]) if add_months(p, 1) == k and k < NOW_YM}


ITA_BASE = 'https://toushin-lib.fwg.ne.jp'


class ItaLib:
    """投資信託協会 投信総合検索ライブラリー（mw_investable_valmom と同じ取り方）。UA に個人の連絡先を載せない"""
    def __init__(self):
        cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        self.op.addheaders = [('User-Agent', M.UA['User-Agent'])]
        self.op.open(ITA_BASE + '/FdsWeb/FDST000000', timeout=60).read()

    def search(self, kw):
        fields = ['s_investAssetKindCd', 's_investArea3kindCd', 's_instCd', 's_fdsInstCd', 's_dcFundCD', 't_investArea10kindCd', 't_investAssetKindCd',
                  't_instCd', 't_fdsInstCd', 's_investArea10kindCd', 's_setlFqcy', 's_dividend1y', 's_totalNetAssets', 's_nowToRedemptionDate',
                  's_establishedDateToNow', 's_isinCd']
        body = {f: [] for f in fields}
        body.update({'t_keyword': kw, 't_kensakuKbn': '1', 't_searchInfoFlag': '1', 'startNo': 0, 'draw': 1, 'searchBtnClickFlg': True})
        req = urllib.request.Request(ITA_BASE + '/FdsWeb/FDST999900/fundDataSearch', data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest',
                                              'Referer': ITA_BASE + '/FdsWeb/FDST999900', 'User-Agent': M.UA['User-Agent']})
        d = json.loads(self.op.open(req, timeout=60).read().decode())
        return (d.get('searchResultInfo') or {}).get('resultInfoMapList') or []

    def csv(self, isin, assoc):
        return self.op.open(f'{ITA_BASE}/FdsWeb/FDST030000/csv-file-download?isinCd={isin}&associFundCd={assoc}', timeout=120).read()


_ITA = {}
UNIT_FIX = {}


def ita():
    if 'lib' not in _ITA:
        _ITA['lib'] = ItaLib()
    return _ITA['lib']


def ita_monthly(isin, assoc, key=None):
    """基準価額＋分配金（1万口あたり・分配落ち日に足し戻す）→ 月末 → 月次。単位の変わり目は 10 のべきで割り戻し、外れる日は打ち切る"""
    key = key or isin
    p = os.path.join(M.CACHE, f'ita_{isin}.csv')
    if not (os.path.exists(p) and os.path.getsize(p) > 1000 and time.time() - os.path.getmtime(p) < 7 * 86400):
        b = ita().csv(isin, assoc)
        tmp = f'{p}.{os.getpid()}.tmp'
        open(tmp, 'wb').write(b); os.replace(tmp, p)
        time.sleep(0.6)
    rows = []
    for ln in open(p, 'rb').read().decode('shift_jis', 'replace').splitlines()[1:]:
        c = ln.split(',')
        if len(c) < 4 or '年' not in c[0]:
            continue
        try:
            nav = float(c[1])
        except ValueError:
            continue
        d = int(c[0][0:4]) * 10000 + int(c[0][5:7]) * 100 + int(c[0][8:10])
        dist = float(c[3]) if c[3].strip() not in ('', '-') else 0.0  # 空欄＝その日に分配が無い（欠測ではない）
        rows.append((d, nav, dist))
    rows.sort()
    tr, prev, last = None, None, {}
    for d, nav, dist in rows:
        if prev is None:
            tr = 1.0
        else:
            f = (nav + dist) / prev
            if f > 5 or f < 0.2:
                p10 = 10 ** round(math.log10(f))
                if 0.8 <= f / p10 <= 1.25:
                    UNIT_FIX.setdefault(key, []).append({'date': d, 'raw_ratio': round(f, 4), 'divided_by': p10})
                    f = f / p10
                else:
                    UNIT_FIX.setdefault(key, []).append({'date': d, 'raw_ratio': round(f, 4), 'action': '打ち切り'})
                    break
            tr = tr * f
        prev = nav
        last[d // 100] = tr
    ks = sorted(k for k in last if k < NOW_YM)
    return {k: last[k] / last[p_] - 1 for p_, k in zip(ks, ks[1:]) if add_months(p_, 1) == k}


def ita_fee(isin=None, kw=None):
    """信託報酬（税抜・税込）と NISA の旗。ISIN で一致したものだけ（推測で埋めない）"""
    p = os.path.join(M.CACHE, 'jnb_ita_meta.json')
    cache = json.load(open(p)) if os.path.exists(p) else {}
    ck = f'{isin}|{kw}'
    if ck in cache:
        return cache[ck]
    res = {'isin': isin, 'kw': kw}
    try:
        hits = ita().search(kw)
        time.sleep(0.5)
        if isin:
            hit = next((h for h in hits if h.get('isinCd') == isin), None)
        else:
            cand = [h for h in hits if str(h.get('isinCd', '')).startswith('JP3')]
            hit = cand[0] if len(cand) == 1 else None
            if len(cand) != 1:
                res['candidates'] = [(h.get('fundNm'), h.get('isinCd')) for h in cand[:8]]
        if hit:
            try:
                tr = float(hit.get('trustReward'))
            except (TypeError, ValueError):
                tr = None
            res.update({'name': hit.get('fundNm'), 'isin_found': hit.get('isinCd'), 'established': str(hit.get('establishedDate'))[:10],
                        'fee_ex_tax_pct': tr, 'fee_incl_tax_pct': round(tr * 1.1, 4) if tr is not None else None,
                        'net_assets_mil_jpy': hit.get('totalNetAssets'), 'nisaFlg_raw': hit.get('nisaFlg'), 'nisaGrowthFlg_raw': hit.get('nisaGrowthFlg')})
    except Exception as e:  # noqa
        res['error'] = str(e)[:200]
    cache[ck] = res
    json.dump(cache, open(p, 'w'), ensure_ascii=False)
    return res


YJUMPS = {}


def yahoo_local(t):
    """mw_common.yahoo と同じ URL・同じキャッシュを読むが、月を取引所の現地時刻（meta.gmtoffset）で切る。
    2026-09-28 この角度で判明: mw_common.yahoo は UTC で月を切るので、東証銘柄の月足（JST の月初 00:00＝前日 15:00 UTC）が
    1か月前に付き、途中の今月の足が『先月』として残る（1698.T の Yahoo と投信協会の基準価額の月次の相関 0.03）。米国銘柄は影響なし"""
    import urllib.parse
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}?period1=0&period2={int(time.time())}&interval=1mo&events=div%2Csplit'
    j = json.loads(M.get(u, name=f'yh_{t.replace("^", "IDX_").replace("=", "_")}_1mo.json', max_age_days=3))
    r = j['chart']['result'][0]
    off = r['meta'].get('gmtoffset') or 0
    adj = r['indicators'].get('adjclose', [{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    px = {}
    for ts, a in zip(r['timestamp'], adj):
        if a is None:
            continue
        d = datetime.datetime.utcfromtimestamp(ts + off)
        px[d.year * 100 + d.month] = a  # 同じ月の後の点（途中の今月の現値）が上書きし、下で今月ごと落とす
    px = {k: v for k, v in px.items() if k < NOW_YM}
    ks = sorted(px)
    return {k: px[k] / px[p] - 1 for p, k in zip(ks, ks[1:]) if add_months(p, 1) == k}


def yh(t):
    r = yahoo_local(t)
    j = [(k, round(v * 100, 1)) for k, v in sorted(r.items()) if abs(v) > 0.40]
    if j:
        YJUMPS[t] = j
    return r


# ───────────────────────── 統計の小道具 ─────────────────────────
def ols_nw(y, X, lag=12):
    y, X = np.asarray(y, float), np.asarray(X, float)
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X)
    u = X * e[:, None]
    Sm = u.T @ u
    for L in range(1, lag + 1):
        G = u[L:].T @ u[:-L]
        Sm += (1 - L / (lag + 1)) * (G + G.T)
    se = np.sqrt(np.diag(XtXi @ Sm @ XtXi))
    r2_ = 1 - e.var() / y.var() if y.var() > 0 else None
    return b, b / se, r2_


def ser_stats(r, a=None, z=None):
    ks = sorted(m for m in r if (a is None or m >= a) and (z is None or m <= z))
    if len(ks) < 24:
        return None
    x = [r[k] for k in ks]
    return {'from': ks[0], 'to': ks[-1], 'cagr': r2(M.cagr(x) * 100), 'vol': r2(S.stdev(x) * math.sqrt(12) * 100, 1), 'maxdd': r2(M.maxdd({k: r[k] for k in ks}) * 100, 1)}


def evaluate(rid, fam, label, s, b, turnover, repl=None, extra=None):
    """格付け用の一式（s・b は同じ基準＝円の総リターンどうし）"""
    ms = sorted(set(s) & set(b))
    s, b = {m: s[m] for m in ms}, {m: b[m] for m in ms}
    rec = {'id': rid, 'family': fam, 'label': label, 'turnover': turnover,
           'full': M.excess_stats(s, b), 'train': M.excess_stats(s, b, z=M.TRAIN_END), 'hold': M.excess_stats(s, b, a=M.HOLD_START),
           'recent': M.excess_stats(s, b, a=M.RECENT_START), 'fresh_2023_04': M.excess_stats(s, b, a=FRESH),
           'cost_hold': M.excess_stats(M.apply_cost(s, turnover, 0.001), b, a=M.HOLD_START),
           'cost_hold_030': M.excess_stats(M.apply_cost(s, turnover, 0.003), b, a=M.HOLD_START),
           'roll20': M.rolling(s, b, 20), 'dca20': M.dca(s, b, 20),
           'maxdd': {'s': r2(M.maxdd(s) * 100, 1), 'b': r2(M.maxdd(b) * 100, 1)} if ms else None,
           'repl': repl}
    if extra:
        rec.update(extra)
    return rec


def finish_family(rows):
    hol = M.holm({r['id']: (r.get('hold') or {}).get('p') for r in rows if r.get('hold')})
    for r in rows:
        r['family_size'] = len(rows)
        r['holm_p'] = hol.get(r['id'])
        tr = r.get('train')
        tr_eff = tr if (tr and tr['years'] >= 15) else None
        if tr and tr['years'] < 15:
            r['train_note'] = f"訓練期間 {tr['years']}年＜15年＝全体の事前登録により C1 不合格側"
        g, c = M.grade(r.get('full'), tr_eff, r.get('hold'), r.get('roll20'), cost_hold=r.get('cost_hold'), repl=r.get('repl'), family_holm_p=r['holm_p'])
        r['grade'], r['criteria'] = g, c
    return rows


def fmt(r):
    t, h, f = r.get('train') or {}, r.get('hold') or {}, r.get('full') or {}
    return (f"{r['id']:28s} {r.get('grade', '-'):2s} train {t.get('ex_ann')!s:>6} t{t.get('t')!s:>5} | hold {h.get('ex_ann')!s:>6} t{h.get('t')!s:>5} "
            f"cg{h.get('cagr_diff')!s:>6} | full t{f.get('t')!s:>5} | roll {((r.get('roll20') or {}).get('win_rate'))} | repl {(r.get('repl') or {}).get('positive')}/{(r.get('repl') or {}).get('regions')} holm {r.get('holm_p')}")


# ───────────────────────── P1・X1（French の大型の角） ─────────────────────────
FR_COLS = {'BM': ('Japan_25_Portfolios_ME_BE-ME', 'BIG HiBM', 'ME4 BM5'), 'OP': ('Japan_25_Portfolios_ME_OP', 'BIG HiOP', 'ME4 OP5'),
           'PR': ('Japan_25_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 'ME4 PRIOR5')}
TURN = {'BM': 0.5, 'OP': 0.4, 'PR': 1.8}


def fr_legs(region):
    """地域の 25分割から BIG/ME4 の角の脚（米ドル）"""
    out = {}
    for k, (nm, big, me4) in FR_COLS.items():
        d = fr_vw(nm.replace('Japan', region))
        out[k] = {'big': d[big], 'me4': d[me4]}
    return out


def rule_series(legs, rule):
    b = lambda k: legs[k]['big']
    b45 = lambda k: mix([legs[k]['me4'], legs[k]['big']])
    if rule == 'P1_VM':
        return mix([b('BM'), b('PR')])
    if rule == 'P1_VQ':
        return mix([b('BM'), b('OP')])
    if rule == 'P1_VQM':
        return mix([b('BM'), b('OP'), b('PR')])
    if rule == 'X1_VM45':
        return mix([b45('BM'), b45('PR')])
    if rule == 'X1_VQM45':
        return mix([b45('BM'), b45('OP'), b45('PR')], [0.5, 0.25, 0.25])
    raise KeyError(rule)


RULE_TURN = {'P1_VM': (TURN['BM'] + TURN['PR']) / 2, 'P1_VQ': (TURN['BM'] + TURN['OP']) / 2, 'P1_VQM': (TURN['BM'] + TURN['OP'] + TURN['PR']) / 3,
             'X1_VM45': (TURN['BM'] + TURN['PR']) / 2, 'X1_VQM45': 0.5 * TURN['BM'] + 0.25 * TURN['OP'] + 0.25 * TURN['PR']}
RULE_LABEL = {'P1_VM': '大型の割安＋勢い（BIG HiBM・BIG HiPRIOR 半々）', 'P1_VQ': '大型の割安＋質（BIG HiBM・BIG HiOP 半々）',
              'P1_VQM': '大型の割安＋質＋勢い（1/3ずつ）', 'X1_VM45': '中大型の割安＋勢い（ME4・ME5 の角）', 'X1_VQM45': '中大型の割安厚め＋質＋勢い'}


def run_french(rules, fam, jp_legs, jp_mkt_yen, repl_legs, repl_mkt):
    rows, series = [], {}
    for rule in rules:
        s_usd = rule_series(jp_legs, rule)
        s_yen = to_jpy(s_usd)
        series[rule] = s_yen
        det, det_h = {}, {}
        for reg in repl_legs:
            sr = rule_series(repl_legs[reg], rule)
            st = M.excess_stats(sr, repl_mkt[reg])
            sh = M.excess_stats(sr, repl_mkt[reg], a=M.HOLD_START)
            if st:
                det[reg] = {'ex_ann': st['ex_ann'], 't': st['t'], 'years': st['years']}
            if sh:
                det_h[reg] = {'ex_ann': sh['ex_ann'], 't': sh['t']}
        repl = {'regions': len(det), 'positive': sum(1 for v in det.values() if v['ex_ann'] > 0), 'detail': det, 'hold_detail_reported': det_h}
        usd_mkt = {m: v for m, v in JP_MKT_USD.items()}
        rec = evaluate(rule, fam, RULE_LABEL[rule] + '（French Japan・円）', s_yen, jp_mkt_yen, RULE_TURN[rule], repl,
                       extra={'source': 'French Japan 25分割（Value Weight）→ 円（DEXJPUS）', 'benchmark': 'French Japan Mkt（Mkt-RF＋RF）→ 円',
                              'usd_check': {'full': M.excess_stats(s_usd, usd_mkt), 'hold': M.excess_stats(s_usd, usd_mkt, a=M.HOLD_START)}})
        rows.append(rec)
    finish_family(rows)
    for r in rows:
        log(' ', fmt(r))
    return rows, series


# ───────────────────────── X2（JKP 日本 vw の再現） ─────────────────────────
X2_RULES = {'X2_DIV': [('div12m_me', '3.0')], 'X2_VM': [('be_me', '3.0'), ('ret_12_1', '3.0')],
            'X2_VQM': [('be_me', '3.0'), ('qmj', '3.0'), ('ret_12_1', '3.0')]}
X2_TURN = {'div12m_me': 0.6, 'be_me': 0.6, 'qmj': 0.6, 'ret_12_1': 1.8}
JKP_REPL = ['aus', 'aut', 'bel', 'can', 'che', 'deu', 'dnk', 'esp', 'fin', 'fra', 'gbr', 'hkg', 'irl', 'isr', 'ita', 'nld', 'nor', 'nzl', 'prt', 'sgp', 'swe']


def run_x2(pf_jp, jkp_mkt_yen):
    rows, series = [], {}
    side_check = {}
    for k in ('div12m_me', 'be_me', 'ret_12_1', 'qmj'):
        try:
            side_check[k] = M.jkp_good_side('jpn', k, 'vw', upto=M.TRAIN_END)[0]
        except Exception as e:  # noqa
            side_check[k] = f'取得失敗 {str(e)[:80]}'
    repl_pf = {}
    for c in JKP_REPL:
        try:
            repl_pf[c] = (jkp_all(c), M.jkp_mkt(c, 'vw'))
        except Exception as e:  # noqa
            log('  repl 取得失敗', c, str(e)[:100])
    for rid, comps in X2_RULES.items():
        s_ex = jkp_strat(pf_jp, comps, 30)
        s_yen = to_jpy(tot_usd(s_ex))
        series[rid] = s_yen
        det = {}
        for c, (pfc, mk) in repl_pf.items():
            sc = jkp_strat(pfc, comps, 10)
            ms = sorted(set(sc) & set(mk))
            if len(ms) < 120:
                continue
            st = M.excess_stats(sc, mk)
            if st:
                det[c] = {'ex_ann': st['ex_ann'], 't': st['t'], 'years': st['years']}
        repl = {'regions': len(det), 'positive': sum(1 for v in det.values() if v['ex_ann'] > 0), 'detail': det}
        to = sum(X2_TURN[k] for k, _ in comps) / len(comps)
        rec = evaluate(rid, 'X2', '＋'.join(k for k, _ in comps) + '（JKP 日本 vw・第3分位・n≥30・円）', s_yen, jkp_mkt_yen, to, repl,
                       extra={'source': 'JKP jpn all_factors vw（超過）＋French RF → 円', 'benchmark': 'JKP jpn mkt vw ＋ RF → 円',
                              'duplicate_of': 'mw_japan（米ドル・同じ規則の系統）＝プログラム全体では重複の検定',
                              'side_check_train_only': {k: side_check.get(k) for k, _ in comps}})
        rows.append(rec)
    finish_family(rows)
    for r in rows:
        log(' ', fmt(r))
    return rows, series, side_check


# ───────────────────────── P2（器） ─────────────────────────
MSCI_CODES = {'MSCI_JP_VALUE': 105796, 'MSCI_JP_HDY': 701710, 'MSCI_JP_MOM': 703763, 'MSCI_JP_QUAL': 145817, 'MSCI_JP_SNQ': 710164}
MSCI_LAUNCH = {'MSCI_JP_VALUE': 199712, 'MSCI_JP_HDY': 201201, 'MSCI_JP_MOM': 201312, 'MSCI_JP_QUAL': 201212, 'MSCI_JP_SNQ': None}
MSCI_FEE = {'MSCI_JP_HDY': 0.209}  # 対応する東証ETF（1478）の信託報酬。他は目安 0.2
ETF_FEE_KW = {'1489.T': '日経平均高配当株５０', '1577.T': '野村日本株高配当７０', '1651.T': 'ＴＯＰＩＸ高配当４０', '1478.T': 'ジャパン高配当利回り',
              '1698.T': '東証配当フォーカス', '2529.T': '野村株主還元７０', '1494.T': '高配当日本株', '2564.T': 'スーパーディビィデンド',
              '1399.T': '高配当低ボラティリティ'}
ETF_ISIN = {'1698.T': 'JP3047170000', '1577.T': 'JP3047560002', '1478.T': 'JP3048150001',
            # 2026-09-28 第1回の実行で検索語が複数の ETF に当たり信託報酬が空欄になった5本を、検索結果の名前で ISIN に固定（取り方の誤りの修正）
            '1489.T': 'JP3048390003', '1651.T': 'JP3048490001', '1494.T': 'JP3048440006', '2564.T': 'JP3049050002', '1399.T': 'JP3048170009',
            '2529.T': 'JP3048890002'}
US_ETF_ER = {'FJP': 0.81, 'DFJ': 0.58, 'DXJ': 0.48}
FUND_KW = {'FUND_SMT_DIVARISTO': '日本株配当貴族', 'FUND_NIKKEI_HDY': '日経平均高配当利回り株ファンド', 'FUND_DC_ACTIVE_VALUE': 'ＤＣつみたて　アクティブ',
           'FUND_ONE_HDY_JAPAN': '高配当利回り厳選ジャパン', 'FUND_OOBUNE_JAPAN': 'おおぶねＪＡＰＡＮ', 'FUND_EMAXIS_QUAL150': 'ＪＡＰＡＮクオリティ'}


def paper_active(pf_jp, jkp_mkt_ex):
    """紙の上乗せ（脚の第3分位 − JKP 日本 mkt vw・米ドルの超過どうしの差）"""
    act = {}
    for leg, k in (('value', 'be_me'), ('div', 'div12m_me'), ('mom', 'ret_12_1'), ('qual', 'qmj')):
        s = jkp_strat(pf_jp, [(k, '3.0')], 30)
        act[leg] = {m: s[m] - jkp_mkt_ex[m] for m in s if m in jkp_mkt_ex}
    act['vm'] = {m: 0.5 * act['value'][m] + 0.5 * act['mom'][m] for m in set(act['value']) & set(act['mom'])}
    return act


def capture(vs, bench, act, leg):
    ms = sorted(m for m in set(vs) & set(bench) & set(act['value']) & set(act['div']) & set(act['mom']) & set(act['qual']) & set(act[leg]) if m <= JKP_END)
    if len(ms) < 36:
        return {'months': len(ms), 'note': '36か月未満（回帰しない）'}
    y = [vs[m] - bench[m] for m in ms]
    x = [act[leg][m] for m in ms]
    b1, t1, rr1 = ols_nw(y, np.column_stack([np.ones(len(ms)), x]))
    X4 = np.column_stack([np.ones(len(ms))] + [[act[k][m] for m in ms] for k in ('value', 'div', 'mom', 'qual')])
    b4, t4, rr4 = ols_nw(y, X4)
    pm, vm = S.mean(x) * 1200, S.mean(y) * 1200
    return {'months': len(ms), 'from': ms[0], 'to': ms[-1], 'leg': leg,
            'one_factor': {'beta': r2(b1[1], 3), 't_beta': r2(t1[1]), 'alpha_ann': r2(b1[0] * 1200), 't_alpha': r2(t1[0]), 'r2': r2(rr1, 3)},
            'four_factor': {'beta_value': r2(b4[1], 3), 't_value': r2(t4[1]), 'beta_div': r2(b4[2], 3), 't_div': r2(t4[2]),
                            'beta_mom': r2(b4[3], 3), 't_mom': r2(t4[3]), 'beta_qual': r2(b4[4], 3), 't_qual': r2(t4[4]),
                            'alpha_ann': r2(b4[0] * 1200), 't_alpha': r2(t4[0]), 'r2': r2(rr4, 3)},
            'paper_active_ann': r2(pm), 'vehicle_active_ann': r2(vm), 'capture_ratio': r2(vm / pm, 2) if pm else None,
            'corr': r2(M.corr(x, y), 3), '_alpha_m': float(b1[0]), '_beta': float(b1[1])}


def run_p2(act, mj_g, mj_n, tpx):
    specs = PRE['families']['P2_vehicles']['members']
    rows, series, fees = [], {}, {}
    for vid, sp in specs.items():
        try:
            if vid.startswith('MSCI_'):
                s = msci(MSCI_CODES[vid], 'GRTR')
                s_net = msci(MSCI_CODES[vid], 'NETR')
            elif vid.startswith('FUND_'):
                s = ita_monthly(sp['isin'], sp['assoc'], vid)
                s_net = None
            elif vid.endswith('.T'):
                s = yh(vid)
                s_net = None
            else:
                s = to_jpy(yh(vid))
                s_net = None
        except Exception as e:  # noqa
            rows.append({'id': vid, 'family': 'P2', 'label': sp['name'], 'error': str(e)[:200], 'grade': 'C', 'report_only': True})
            continue
        series[vid] = s
        # 費用
        if vid.startswith('FUND_'):
            fees[vid] = ita_fee(sp['isin'], FUND_KW.get(vid))
        elif vid.endswith('.T'):
            fees[vid] = ita_fee(ETF_ISIN.get(vid), ETF_FEE_KW.get(vid))
        elif vid in US_ETF_ER:
            fees[vid] = {'expense_ratio_pct': US_ETF_ER[vid], 'src': 'out/broker_lineup.json'}
        else:
            fees[vid] = {'fee_equiv_pct': MSCI_FEE.get(vid, 0.2), 'note': '指数（器の費用は引かれていない）。cost_hold は目安の費用を引いた版'}
        fee_equiv = MSCI_FEE.get(vid, 0.2) if vid.startswith('MSCI_') else 0.0
        s_fee = {m: v - fee_equiv / 1200 for m, v in s.items()}
        rec = evaluate(vid, 'P2', sp['name'] + ' 対 MSCI Japan（円・gross）', s, mj_g, 0.0, None,
                       extra={'report_only': True, 'leg': sp['leg'], 'src': sp.get('src', 'MSCI end-of-month API'),
                              'launch': sp.get('launch'), 'fee': fees[vid]})
        rec['cost_hold'] = M.excess_stats(s_fee, mj_g, a=M.HOLD_START)  # 指数は器の費用の目安を引く・器は実績なので同じ
        rec['vs_topix_1306nav'] = {'full': M.excess_stats(s, tpx), 'hold': M.excess_stats(s, tpx, a=M.HOLD_START), 'fresh_2023_04': M.excess_stats(s, tpx, a=FRESH)}
        if s_net is not None:
            rec['net_vs_net'] = {'full': M.excess_stats(s_net, mj_n), 'hold': M.excess_stats(s_net, mj_n, a=M.HOLD_START)}
        lm = MSCI_LAUNCH.get(vid)
        if lm:
            rec['post_launch'] = M.excess_stats(s, mj_g, a=add_months(lm, 1))
        rec['dca10'] = M.dca(s, mj_g, 10)
        rec['capture'] = capture(s, mj_g, act, sp['leg'])
        rec['series_stats'] = ser_stats(s)
        rows.append(rec)
    finish_family(rows)
    for r in rows:
        if r.get('error'):
            log('  P2 取得失敗', r['id'], r['error'])
            continue
        f, h, fr = r.get('full') or {}, r.get('hold') or {}, r.get('fresh_2023_04') or {}
        cp = (r.get('capture') or {}).get('one_factor') or {}
        log(f"  {r['id']:22s} {r['grade']} {f.get('from')}〜 全 {f.get('ex_ann')} t{f.get('t')} | 2007〜 {h.get('ex_ann')} t{h.get('t')} | 2023-04〜 {fr.get('ex_ann')} "
            f"| 載り β{cp.get('beta')} t{cp.get('t_beta')} α{cp.get('alpha_ann')} 比{(r.get('capture') or {}).get('capture_ratio')}")
    return rows, series, fees


# ───────────────────────── P3（投資家の単位の積立） ─────────────────────────
def sim_gap(rets, w, months, us, ylds, tax='T0', amount=1.0, nisa_cap=None, add=None):
    """積立金だけで組み直す（不足按分）。rets=[{ym: r}]・w=目標・us=米国株か・ylds=配当利回り（年・小数）
    add=(袖の番号, 年率) で一定の上乗せを足す。戻り値 (売る前の最終額, 売った後の最終額, 払い込み)"""
    k = len(rets)
    Vn, Vt, Bt = [0.0] * k, [0.0] * k, [0.0] * k
    paid = 0.0
    dn = [ylds[i] / 12 * (US_WH if us[i] else 0.0) for i in range(k)]
    dt = [ylds[i] / 12 * ((US_WH + (1 - US_WH) * TAX) if us[i] else TAX) for i in range(k)]
    reinv = [ylds[i] / 12 * ((1 - US_WH) * (1 - TAX) if us[i] else (1 - TAX)) for i in range(k)]
    for m in months:
        tot = sum(Vn) + sum(Vt)
        short = [max(0.0, w[i] * (tot + amount) - (Vn[i] + Vt[i])) for i in range(k)]
        ss = sum(short)
        alloc = [amount * x / ss for x in short] if ss > 0 else [amount * wi for wi in w]
        if tax == 'T0':
            fn = 1.0
        elif tax == 'T2':
            fn = 0.0
        else:
            room = max(0.0, nisa_cap - paid)
            fn = min(1.0, room / amount)
        paid += amount
        for i in range(k):
            Vn[i] += alloc[i] * fn
            Vt[i] += alloc[i] * (1 - fn)
            Bt[i] += alloc[i] * (1 - fn)
        for i in range(k):
            r = rets[i][m] + (add[1] / 12 if add and add[0] == i else 0.0)
            Vn[i] *= 1 + r - dn[i]
            Bt[i] += Vt[i] * reinv[i]
            Vt[i] *= 1 + r - dt[i]
    pre = sum(Vn) + sum(Vt)
    gain = sum(Vt) - sum(Bt)
    post = pre - TAX * max(0.0, gain)
    return pre, post, paid


def windows(months_all, n):
    ms = sorted(months_all)
    out = []
    for i in range(0, len(ms) - n + 1):
        w = ms[i:i + n]
        if add_months(w[0], n - 1) == w[-1]:
            out.append(w)
    return out


def qdist(vals):
    v = sorted(vals)
    q = lambda p: v[min(len(v) - 1, int(p * (len(v) - 1) + 0.5))]
    return {'n': len(v), 'min': r2(v[0], 3), 'p10': r2(q(0.1), 3), 'p25': r2(q(0.25), 3), 'median': r2(q(0.5), 3), 'p75': r2(q(0.75), 3), 'p90': r2(q(0.9), 3), 'max': r2(v[-1], 3)}


def ratio_block(rows):
    """rows=[(起点, 比)] → 勝率・分布・最悪/最良の起点"""
    if not rows:
        return None
    v = [r for _, r in rows]
    wst = min(rows, key=lambda x: x[1]); bst = max(rows, key=lambda x: x[1])
    return {'windows': len(rows), 'first_start': rows[0][0], 'last_start': rows[-1][0], 'win_rate': r2(sum(1 for x in v if x > 1) / len(v), 3),
            'dist': qdist(v), 'worst': [wst[0], r2(wst[1], 3)], 'best': [bst[0], r2(bst[1], 3)]}


YLD = {'NDX': 0.008, 'SMH': 0.009, 'SPX': 0.017, 'JMKT': 0.018, 'JTILT': 0.033}


def run_p3(CUR, SPX, JS, yield_of):
    """CUR={'NDX':…, 'SMH':…}（円）・SPX（円）・JS={袖名: 円}"""
    res = {}
    for jn, J in JS.items():
        base = set(CUR['NDX']) & set(CUR['SMH']) & set(SPX) & set(J)
        rec = {'sleeve_stats': ser_stats(J), 'by_years': {}}
        jy = yield_of(jn)
        for yrs in (20, 15, 10):
            wins = windows(base, yrs * 12)
            if not wins:
                rec['by_years'][yrs] = None
                continue
            taxes = ('T0', 'T1', 'T2') if yrs == 20 else ('T0',)
            blk = {}
            for tax in taxes:
                amt = 136000.0 if tax == 'T1' else 1.0
                cap = 28_800_000.0 if tax == 'T1' else None
                cur_rows, spx_rows = [], []
                per_x = {x: {'vs_cur': [], 'vs_spx': [], 'mult_mix': []} for x in (0.1, 0.2, 0.3)}
                mult_cur, mult_spx = [], []
                for w in wins:
                    cpre, cpost, paid = sim_gap([CUR['NDX'], CUR['SMH']], [0.75, 0.25], w, [True, True], [YLD['NDX'], YLD['SMH']], tax, amt, cap)
                    spre, spost, _ = sim_gap([SPX], [1.0], w, [True], [YLD['SPX']], tax, amt, cap)
                    cv, sv = (cpre, spre) if tax == 'T0' else (cpost, spost)
                    mult_cur.append(cv / paid); mult_spx.append(sv / paid)
                    for x in (0.1, 0.2, 0.3):
                        mpre, mpost, _ = sim_gap([CUR['NDX'], CUR['SMH'], J], [0.75 * (1 - x), 0.25 * (1 - x), x], w, [True, True, False],
                                                 [YLD['NDX'], YLD['SMH'], jy], tax, amt, cap)
                        mv = mpre if tax == 'T0' else mpost
                        per_x[x]['vs_cur'].append((w[0], mv / cv)); per_x[x]['vs_spx'].append((w[0], mv / sv)); per_x[x]['mult_mix'].append(mv / paid)
                blk[tax] = {'multiple_current': qdist(mult_cur), 'multiple_sp500': qdist(mult_spx),
                            'by_x': {f'x{int(x * 100)}': {'vs_current': ratio_block(v['vs_cur']), 'vs_sp500': ratio_block(v['vs_spx']), 'multiple_mix': qdist(v['mult_mix'])}
                                     for x, v in per_x.items()}}
                if yrs == 20 and tax == 'T0':
                    blk[tax]['per_window_x20_vs_current'] = [[a, r2(b, 3)] for a, b in per_x[0.2]['vs_cur']]
                if tax != 'T0':
                    blk[tax]['note'] = '最後に全部売ったとした税引後（T1 は月13.6万円・NISA 2,880万円まで）'
            rec['by_years'][yrs] = blk
            d = (blk['T0']['by_x']['x20']['vs_current'] or {})
            log(f"  [P3] {jn} {yrs}年 x20 T0: 窓 {d.get('windows')} 勝率 {d.get('win_rate')} 中央 {(d.get('dist') or {}).get('median')} 最悪 {d.get('worst')}")
        res[jn] = rec
    return res


def break_even(CUR, SPX, JS, yield_of, sleeves):
    out = {}
    for jn in sleeves:
        J = JS[jn]
        base = set(CUR['NDX']) & set(CUR['SMH']) & set(SPX) & set(J)
        wins = windows(base, 240)
        jy = yield_of(jn)
        g_cur, g_spx = [], []
        for w in wins:
            cpre, _, _ = sim_gap([CUR['NDX'], CUR['SMH']], [0.75, 0.25], w, [True, True], [YLD['NDX'], YLD['SMH']])
            spre, _, _ = sim_gap([SPX], [1.0], w, [True], [YLD['SPX']])
            for target, store in ((cpre, g_cur), (spre, g_spx)):
                lo, hi = -0.5, 0.5
                f = lambda g: sim_gap([CUR['NDX'], CUR['SMH'], J], [0.6, 0.2, 0.2], w, [True, True, False], [YLD['NDX'], YLD['SMH'], jy], add=(2, g))[0] - target
                flo, fhi = f(lo), f(hi)
                if flo > 0 or fhi < 0:
                    store.append((w[0], None))
                    continue
                for _ in range(40):
                    mid = (lo + hi) / 2
                    if f(mid) > 0:
                        hi = mid
                    else:
                        lo = mid
                store.append((w[0], (lo + hi) / 2 * 100))
        blk = {}
        for nm, rows in (('vs_current', g_cur), ('vs_sp500', g_spx)):
            v = [g for _, g in rows if g is not None]
            blk[nm] = {'windows': len(rows), 'unbracketed': sum(1 for _, g in rows if g is None), 'g_star_pct_per_year': qdist(v) if v else None,
                       'share_g_le_0': r2(sum(1 for g in v if g <= 0) / len(v), 3) if v else None,
                       'worst_start': max(rows, key=lambda x: -1e9 if x[1] is None else x[1])[0] if v else None}
        out[jn] = blk
        log(f"  [BE1] {jn}: 今の側と並ぶ上乗せ g* 中央 {(blk['vs_current']['g_star_pct_per_year'] or {}).get('median')}%/年 "
            f"p10 {(blk['vs_current']['g_star_pct_per_year'] or {}).get('p10')} p90 {(blk['vs_current']['g_star_pct_per_year'] or {}).get('p90')}"
            f" | 対 S&P500 中央 {(blk['vs_sp500']['g_star_pct_per_year'] or {}).get('median')}")
    return out


# ───────────────────────── B（市場の差の基礎率） ─────────────────────────
def jst():
    import openpyxl
    wb = openpyxl.load_workbook(os.path.join(M.CACHE, 'jst_R6.xlsx'), read_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    hdr = next(rows)
    ix = {k: hdr.index(k) for k in ('year', 'country', 'eq_tr', 'xrusd')}
    d = collections.defaultdict(dict)
    for r in rows:
        c = r[ix['country']]
        if c in ('Japan', 'USA'):
            d[c][int(r[ix['year']])] = (r[ix['eq_tr']], r[ix['xrusd']])
    return d


def gap_rates(gaps, es):
    v = [g for _, g in gaps]
    if not v:
        return None
    return {'windows': len(v), 'first_start': gaps[0][0], 'last_start': gaps[-1][0], 'gap_pct_dist': qdist(v),
            'share_gap_ge_minus_e': {str(e): r2(sum(1 for g in v if g >= -e) / len(v), 3) for e in es},
            'worst': [min(gaps, key=lambda x: x[1])[0], r2(min(v), 2)], 'best': [max(gaps, key=lambda x: x[1])[0], r2(max(v), 2)]}


def monthly_gaps(a, b, n=240):
    ks = sorted(set(a) & set(b))
    out = []
    for w in windows(ks, n):
        ga = math.exp(math.fsum(math.log1p(a[k]) for k in w) * 12 / n) - 1
        gb = math.exp(math.fsum(math.log1p(b[k]) for k in w) * 12 / n) - 1
        out.append((w[0], (ga - gb) * 100))
    return out


def run_b(es, jp_local_fr, us_yen, jp_mkt_yen_fr, cur_yen):
    out = {}
    d = jst()
    jp, us = d['Japan'], d['USA']
    ann = {}
    for y in sorted(jp):
        if y - 1 not in jp:
            continue
        a, xr = jp[y]; _, xr0 = jp[y - 1]
        b = us.get(y, (None, None))[0]
        if None in (a, xr, xr0, b):
            continue
        ann[y] = (a, (1 + b) * xr / xr0 - 1)
    gaps, gaps_ex = [], []
    for y0 in range(min(ann), max(ann) - 18):
        ys = list(range(y0, y0 + 20))
        if any(y not in ann for y in ys):
            continue
        gj = math.exp(math.fsum(math.log1p(ann[y][0]) for y in ys) / 20) - 1
        gu = math.exp(math.fsum(math.log1p(ann[y][1]) for y in ys) / 20) - 1
        gaps.append((y0, (gj - gu) * 100))
        if not any(1941 <= y <= 1950 for y in ys):
            gaps_ex.append((y0, (gj - gu) * 100))
    out['JST_annual_1886_2020'] = gap_rates(gaps, es)
    out['JST_ex_1941_1950'] = gap_rates(gaps_ex, es)
    out['JST_years_used'] = {'first': min(ann), 'last': max(ann), 'n': len(ann), 'missing_japan_years': [y for y in range(min(ann), max(ann) + 1) if y not in ann]}
    out['French_1975_monthly'] = gap_rates(monthly_gaps(jp_local_fr, us_yen), es)
    out['Japan_mkt_minus_current_side_1985'] = gap_rates(monthly_gaps(jp_local_fr, cur_yen), es)
    out['period_gaps_japan_minus_us_yen'] = {}
    for lab, a, z in (('1990-01〜2012-12', 199001, 201212), ('1990-01〜2026-08', 199001, 202608), ('2013-01〜2026-08', 201301, 202608),
                      ('1975-01〜1989-12', 197501, 198912), ('2007-01〜2026-08', 200701, 202608)):
        ks = [k for k in sorted(set(jp_local_fr) & set(us_yen)) if a <= k <= z]
        if len(ks) < 24:
            continue
        out['period_gaps_japan_minus_us_yen'][lab] = {'japan_cagr': r2(M.cagr([jp_local_fr[k] for k in ks]) * 100), 'us_cagr_yen': r2(M.cagr([us_yen[k] for k in ks]) * 100),
                                                     'gap': r2((M.cagr([jp_local_fr[k] for k in ks]) - M.cagr([us_yen[k] for k in ks])) * 100)}
    for k in ('JST_annual_1886_2020', 'JST_ex_1941_1950', 'French_1975_monthly', 'Japan_mkt_minus_current_side_1985'):
        v = out[k] or {}
        log(f"  [BE2] {k}: 窓 {v.get('windows')} 差の中央 {(v.get('gap_pct_dist') or {}).get('median')} 差≥−e の割合 {v.get('share_gap_ge_minus_e')}")
    return out


# ───────────────────────── F（前向きの模擬） ─────────────────────────
def forward(CUR, SPX, JMKT, A, beta, alpha_m, fee_m, nsim=5000, years=20, seed=20260928):
    ms = sorted(m for m in set(CUR['NDX']) & set(CUR['SMH']) & set(SPX) & set(JMKT) & set(A) if 199011 <= m <= JKP_END)
    X = np.array([[CUR['NDX'][m], CUR['SMH'][m], SPX[m], JMKT[m], A[m]] for m in ms])
    mu = X.mean(axis=0)
    Z = X - mu
    T, n = years * 12, len(ms)
    rng = np.random.default_rng(seed)
    nb = T // 12
    starts = rng.integers(0, n - 12 + 1, size=(nsim, nb))
    idx = (starts[:, :, None] + np.arange(12)[None, None, :]).reshape(nsim, T)
    Zs = Z[idx]  # nsim × T × 5
    out = {'months_used': [ms[0], ms[-1], n], 'hist_means_ann_pct': {k: r2(v * 1200) for k, v in zip(['NDX', 'SMH', 'SPX', 'JMKT', 'A'], mu)},
           'beta': r2(beta, 3), 'alpha_ann': r2(alpha_m * 1200), 'fee_ann': r2(fee_m * 1200, 3), 'scenarios': {}}
    var = Z.var(axis=0)
    var_jsl = float(np.var(Z[:, 3] + beta * Z[:, 4]))
    g_spx = mu[2] - var[2] / 2
    for sc in ('S0', 'S1', 'S2', 'S3_事後'):
        if sc == 'S0':
            m_ndx, m_smh, m_spx, m_j, m_act = mu[0], mu[1], mu[2], mu[3], alpha_m + beta * mu[4]
        elif sc == 'S1':
            m_ndx = m_smh = m_spx = m_j = mu[2]
            m_act = 0.5 * beta * mu[4] - fee_m
        elif sc == 'S2':
            m_ndx = m_smh = m_spx = m_j = mu[2]
            m_act = -fee_m
        else:  # 事後: 対数の成長率を S&P500 にそろえる（算術平均 = g + σ²/2）＋袖は紙の上乗せの半分×β − 費用
            m_ndx, m_smh, m_spx = g_spx + var[0] / 2, g_spx + var[1] / 2, mu[2]
            m_j = g_spx + var_jsl / 2
            m_act = 0.5 * beta * mu[4] - fee_m
        ndx = Zs[:, :, 0] + m_ndx; smh = Zs[:, :, 1] + m_smh
        jsl = Zs[:, :, 3] + m_j + beta * Zs[:, :, 4] + m_act
        dn = [YLD['NDX'] / 12 * US_WH, YLD['SMH'] / 12 * US_WH, 0.0]

        def run(ws, legs):
            k = len(legs)
            V = np.zeros((nsim, k))
            for t in range(T):
                tot = V.sum(axis=1, keepdims=True)
                short = np.maximum(0.0, np.array(ws)[None, :] * (tot + 1.0) - V)
                V = V + short / short.sum(axis=1, keepdims=True)
                for i in range(k):
                    V[:, i] *= 1 + legs[i][:, t] - dn[i]
            return V.sum(axis=1)
        cur = run([0.75, 0.25], [ndx, smh])
        blk = {}
        for x in (0.1, 0.2, 0.3):
            mx = run([0.75 * (1 - x), 0.25 * (1 - x), x], [ndx, smh, jsl])
            rat = mx / cur
            blk[f'x{int(x * 100)}'] = {'p_win': r2(float((rat > 1).mean()), 3), 'ratio_median': r2(float(np.median(rat)), 3),
                                        'ratio_p10': r2(float(np.quantile(rat, 0.1)), 3), 'ratio_p90': r2(float(np.quantile(rat, 0.9)), 3)}
        blk['means_ann_pct'] = {'NDX': r2(m_ndx * 1200), 'SMH': r2(m_smh * 1200), 'JMKT': r2(m_j * 1200), 'sleeve_active': r2(m_act * 1200)}
        out['scenarios'][sc] = blk
        log(f"  [F] {sc}: x20 勝つ確率 {blk['x20']['p_win']} 比の中央 {blk['x20']['ratio_median']} | 平均 {blk['means_ann_pct']}")
    return out


# ───────────────────────── 本体 ─────────────────────────
JP_MKT_USD = {}


def main():
    global FX, RF, JP_MKT_USD
    t0 = time.time()
    FX = fx_monthend()
    ff = M.ff_factors()
    RF = ff['rf']
    out = {'angle': 'jp_nisa_bridge', 'prereg': 'out/' + PRE_NAME, 'prereg_commit': git_sha('out/' + PRE_NAME),
           'global_prereg': 'out/mw_prereg.json', 'global_prereg_commit': git_sha('out/mw_prereg.json')}
    san = {}
    san['US_mkt_cagr_all'] = r2(M.cagr(ff['mkt']) * 100)
    san['US_mkt_cagr_2007'] = r2(M.cagr(M.window(ff['mkt'], M.HOLD_START)) * 100)

    # 日本の市場（円）
    JP_MKT_USD = fr_mkt('Japan')
    jp_mkt_yen = to_jpy(JP_MKT_USD)
    jp_local = fr_intl_japan('Local')
    ks = sorted(set(jp_mkt_yen) & set(jp_local))
    san['FR_Japan_mkt_yen_vs_FRintl_local'] = {'from': ks[0], 'to': ks[-1], 'corr': r2(M.corr([jp_mkt_yen[k] for k in ks], [jp_local[k] for k in ks]), 4),
                                               'cagr_converted': r2(M.cagr([jp_mkt_yen[k] for k in ks]) * 100), 'cagr_local': r2(M.cagr([jp_local[k] for k in ks]) * 100)}
    jkp_mkt_ex = M.jkp_mkt('jpn', 'vw')
    jkp_mkt_usd = tot_usd(jkp_mkt_ex)
    jkp_mkt_yen = to_jpy(jkp_mkt_usd)
    ks = sorted(set(jkp_mkt_usd) & set(JP_MKT_USD))
    san['JKP_vs_French_Japan_mkt_usd'] = {'from': ks[0], 'to': ks[-1], 'corr': r2(M.corr([jkp_mkt_usd[k] for k in ks], [JP_MKT_USD[k] for k in ks]), 4),
                                          'cagr_jkp': r2(M.cagr([jkp_mkt_usd[k] for k in ks]) * 100), 'cagr_french': r2(M.cagr([JP_MKT_USD[k] for k in ks]) * 100)}
    log('sanity', json.dumps(san, ensure_ascii=False))

    # ── P1・X1
    log('== P1（主）')
    jp_legs = fr_legs('Japan')
    repl_legs = {reg: fr_legs(reg) for reg in ('Europe', 'Asia_Pacific_ex_Japan')}
    repl_mkt = {reg: fr_mkt(reg) for reg in repl_legs}
    P1, s_p1 = run_french(['P1_VM', 'P1_VQ', 'P1_VQM'], 'P1', jp_legs, jp_mkt_yen, repl_legs, repl_mkt)
    log('== X1（探索）')
    X1, s_x1 = run_french(['X1_VM45', 'X1_VQM45'], 'X1', jp_legs, jp_mkt_yen, repl_legs, repl_mkt)

    # ── X2
    log('== X2（再現）')
    pf_jp = jkp_all('jpn')
    X2, s_x2, side_check = run_x2(pf_jp, jkp_mkt_yen)

    # ── P2
    log('== P2（器・報告のみ）')
    act = paper_active(pf_jp, jkp_mkt_ex)
    mj_g, mj_n = msci(939200, 'GRTR'), msci(939200, 'NETR')
    tpx = ita_monthly('JP3027630007', '01312017', 'TOPIX1306')
    ks = sorted(set(mj_g) & set(jp_mkt_yen) & set(tpx))
    san['MSCI_Japan_gross_vs_French_vs_1306nav'] = {'from': ks[0], 'to': ks[-1],
                                                    'corr_msci_french': r2(M.corr([mj_g[k] for k in ks], [jp_mkt_yen[k] for k in ks]), 4),
                                                    'corr_msci_1306': r2(M.corr([mj_g[k] for k in ks], [tpx[k] for k in ks]), 4),
                                                    'cagr_msci_gross': r2(M.cagr([mj_g[k] for k in ks]) * 100), 'cagr_french_yen': r2(M.cagr([jp_mkt_yen[k] for k in ks]) * 100),
                                                    'cagr_1306nav': r2(M.cagr([tpx[k] for k in ks]) * 100)}
    P2, s_p2, fees = run_p2(act, mj_g, mj_n, tpx)
    # Yahoo と投信協会の基準価額の照合（同じ ETF）
    chk = {}
    for t, isin, assoc in (('1698.T', 'JP3047170000', '02311105'), ('1577.T', 'JP3047560002', '01313133'), ('1478.T', 'JP3048150001', '4831415A')):
        try:
            a, b = s_p2.get(t) or {}, ita_monthly(isin, assoc, t + '_nav')
            ks = sorted(set(a) & set(b))
            chk[t] = {'months': len(ks), 'corr': r2(M.corr([a[k] for k in ks], [b[k] for k in ks]), 4),
                      'cagr_yahoo_price': r2(M.cagr([a[k] for k in ks]) * 100), 'cagr_nav': r2(M.cagr([b[k] for k in ks]) * 100)}
        except Exception as e:  # noqa
            chk[t] = {'error': str(e)[:150]}
    san['yahoo_price_vs_ita_nav'] = chk
    san['yahoo_jumps_gt_40pct'] = YJUMPS
    san['ita_unit_fixes'] = UNIT_FIX

    # 前向きの器を規則で選ぶ（登録どおり）
    cands = []
    for r in P2:
        vid = r['id']
        if r.get('error') or not (vid.endswith('.T') or vid.startswith('FUND_')):
            continue
        s = s_p2.get(vid) or {}
        nmon = len([m for m in s if m <= 202608])
        fee = (fees.get(vid) or {}).get('fee_incl_tax_pct')
        tb = (((r.get('capture') or {}).get('one_factor')) or {}).get('t_beta')
        ok = nmon >= 108 and fee is not None and fee <= 0.35 and tb is not None
        cands.append({'id': vid, 'months': nmon, 'fee_incl_tax_pct': fee, 't_beta': tb, 'eligible': ok})
    elig = [c for c in cands if c['eligible']]
    pick = sorted(elig, key=lambda c: (-c['t_beta'], c['fee_incl_tax_pct']))[0] if elig else None
    log('  前向きの器（規則で選択）:', pick)
    out['forward_registration_request'] = {
        'rule': PRE['families']['F_forward']['forward_registration_rule'], 'candidates': cands, 'selected': pick,
        'targets': ([{'id': 'FWD_' + pick['id'], 'strategy': pick['id'] + '（月次の総リターン・円）', 'benchmark': '1306 の基準価額＋分配金（TOPIX・投資信託協会）', 'from': 202610}] if pick else [])
        + [{'id': 'FWD_P1_VM', 'strategy': 'P1_VM（French Japan の BIG HiBM・BIG HiPRIOR 半々・円）', 'benchmark': 'French Japan Mkt（円）', 'from': 202609}],
        'note': 'out/mw_forward_prereg.json・night/mw_forward.py は別の角度の持ち物なので書き換えていない。e過程（e≥20）の仕様は mw_forward と同じ作法で親が統合する'}

    # ── P3
    log('== P3（投資家の単位・報告のみ）')
    qqq, ndx, smh = yh('QQQ'), yh('^NDX'), yh('SMH')
    both = sorted(set(qqq) & set(ndx))
    d_hat = (M.cagr([qqq[m] for m in both]) - M.cagr([ndx[m] for m in both])) * 100 + 0.20
    chips = fr_vw('49_Industry_Portfolios')['Chips']
    ndx_side = {m: (qqq[m] - 0.00295 / 12) if m in qqq else (ndx[m] + d_hat / 1200 - 0.00495 / 12) for m in set(ndx) | set(qqq)}
    semi_side = {m: smh[m] if m in smh else chips[m] - 0.0035 / 12 for m in set(chips) | set(smh) if m >= 198501}
    CUR = {'NDX': to_jpy(ndx_side), 'SMH': to_jpy(semi_side)}
    sptr = yh('^SP500TR')
    spx_usd = {m: (sptr[m] if m in sptr else ff['mkt'][m]) - (0.000938 if m in sptr else 0.001) / 12 for m in set(sptr) | set(ff['mkt']) if m >= 197101}
    SPX = to_jpy(spx_usd)
    cur_yen_mix = {m: 0.75 * CUR['NDX'][m] + 0.25 * CUR['SMH'][m] for m in set(CUR['NDX']) & set(CUR['SMH'])}
    ks = sorted(set(jp_mkt_yen) & set(SPX))
    san['Japan_minus_SP500_yen'] = {lab: r2((M.cagr([jp_mkt_yen[k] for k in ks if a <= k <= z]) - M.cagr([SPX[k] for k in ks if a <= k <= z])) * 100)
                                    for lab, a, z in (('1990-07〜2012-12', 199007, 201212), ('1990-07〜2026-08', 199007, 202608), ('2013-01〜2026-08', 201301, 202608))}
    san['ndx_dividend_estimate_pct'] = r2(d_hat, 3)
    # 日本の袖
    best_cap = None
    if pick:
        rp = next(r for r in P2 if r['id'] == pick['id'])
        best_cap = rp['capture']
    JS = {'J0_MKT_FR': {m: v - 0.001 / 12 for m, v in jp_mkt_yen.items()},
          'J0_MKT_JKP': {m: v - 0.001 / 12 for m, v in jkp_mkt_yen.items()},
          'J1_P1VM': {m: v - (1.15 * 0.003 + 0.003) / 12 for m, v in s_p1['P1_VM'].items()},
          'J1_P1VQM': {m: v - (0.9 * 0.003 + 0.003) / 12 for m, v in s_p1['P1_VQM'].items()},
          'J2_DIV': {m: v - (0.6 * 0.003 + 0.003) / 12 for m, v in s_x2['X2_DIV'].items()}}
    if best_cap and best_cap.get('_beta') is not None:
        leg = best_cap['leg']
        JS['J3_CAPT'] = {m: jkp_mkt_yen[m] + best_cap['_alpha_m'] + best_cap['_beta'] * act[leg][m] for m in jkp_mkt_yen if m in act[leg]}
    hdy = msci(701710, 'GRTR')
    JS['J4_HDY_IDX'] = {m: v - 0.00209 / 12 for m, v in hdy.items()}
    yield_of = lambda jn: YLD['JMKT'] if jn.startswith('J0') else YLD['JTILT']
    P3 = run_p3(CUR, SPX, JS, yield_of)
    # 共通の起点の範囲（全袖がそろう窓）
    common = set(CUR['NDX']) & set(CUR['SMH']) & set(SPX)
    for jn in ('J0_MKT_FR', 'J1_P1VM', 'J2_DIV', 'J0_MKT_JKP'):
        common &= set(JS[jn])
    cw = windows(common, 240)
    P3_common = {'first_start': cw[0][0] if cw else None, 'last_start': cw[-1][0] if cw else None, 'windows': len(cw), 'by_sleeve_x20_T0': {}}
    for jn in ('J0_MKT_FR', 'J0_MKT_JKP', 'J1_P1VM', 'J2_DIV'):
        rows = []
        for w in cw:
            c, _, _ = sim_gap([CUR['NDX'], CUR['SMH']], [0.75, 0.25], w, [True, True], [YLD['NDX'], YLD['SMH']])
            mx, _, _ = sim_gap([CUR['NDX'], CUR['SMH'], JS[jn]], [0.6, 0.2, 0.2], w, [True, True, False], [YLD['NDX'], YLD['SMH'], yield_of(jn)])
            rows.append((w[0], mx / c))
        P3_common['by_sleeve_x20_T0'][jn] = ratio_block(rows)

    # ── 事後（格付けに使わない・登録の外）: 実在の器の10年の積立／ETF 側が S&P500 だった場合
    post = {'note': '事後（第2回の実行で足した・登録の外・格付けに使わない）'}
    rv = {}
    mjf = {m: v - 0.001 / 12 for m, v in mj_g.items()}
    for t in ('1698.T', '1577.T', '1478.T'):
        V = s_p2.get(t) or {}
        rec = {}
        for nm, J in ((t, V), ('MSCI_Japan_gross_same_windows', mjf)):
            base = set(CUR['NDX']) & set(CUR['SMH']) & set(SPX) & set(V) & set(J)
            wins = windows(base, 120)
            rows_c, rows_s = [], []
            for w in wins:
                c, _, _ = sim_gap([CUR['NDX'], CUR['SMH']], [0.75, 0.25], w, [True, True], [YLD['NDX'], YLD['SMH']])
                sp, _, _ = sim_gap([SPX], [1.0], w, [True], [YLD['SPX']])
                mx, _, _ = sim_gap([CUR['NDX'], CUR['SMH'], J], [0.6, 0.2, 0.2], w, [True, True, False], [YLD['NDX'], YLD['SMH'], YLD['JTILT']])
                rows_c.append((w[0], mx / c)); rows_s.append((w[0], mx / sp))
            rec[nm] = {'x20_vs_current': ratio_block(rows_c), 'x20_vs_sp500': ratio_block(rows_s)}
        rv[t] = rec
        d_ = (rec[t]['x20_vs_current'] or {})
        log(f"  [事後] 実在 {t} 10年 x20: 窓 {d_.get('windows')} 勝率 {d_.get('win_rate')} 中央 {(d_.get('dist') or {}).get('median')} | 同じ窓の MSCI Japan 中央 {((rec['MSCI_Japan_gross_same_windows']['x20_vs_current'] or {}).get('dist') or {}).get('median')}")
    post['real_vehicles_10y_x20_T0'] = rv
    sb = {}
    for jn in ('J0_MKT_FR', 'J1_P1VM', 'J2_DIV', 'J4_HDY_IDX'):
        J = JS[jn]
        base = set(SPX) & set(J)
        rows = []
        for w in windows(base, 240):
            sp, _, _ = sim_gap([SPX], [1.0], w, [True], [YLD['SPX']])
            mx, _, _ = sim_gap([SPX, J], [0.8, 0.2], w, [True, False], [YLD['SPX'], yield_of(jn)])
            rows.append((w[0], mx / sp))
        sb[jn] = ratio_block(rows)
        log(f"  [事後] S&P500 80＋{jn} 20 対 S&P500 100（20年・T0）: 勝率 {(sb[jn] or {}).get('win_rate')} 中央 {((sb[jn] or {}).get('dist') or {}).get('median')} 最悪 {(sb[jn] or {}).get('worst')}")
    post['sp500_side_plus_japan20_vs_sp500_20y_T0'] = sb

    # ── B
    log('== B（損益分岐・基礎率）')
    BE1 = break_even(CUR, SPX, JS, yield_of, [k for k in ('J0_MKT_FR', 'J1_P1VM', 'J2_DIV', 'J3_CAPT', 'J4_HDY_IDX') if k in JS])
    e_paper = ((next(r for r in P1 if r['id'] == 'P1_VM').get('full')) or {}).get('cagr_diff')
    e_veh = None
    if pick:
        e_veh = ((next(r for r in P2 if r['id'] == pick['id']).get('full')) or {}).get('cagr_diff')
    es = [0, 1, 2, 3, 4] + [e for e in (e_paper, e_veh) if e is not None]
    us_yen = to_jpy(ff['mkt'])
    BE2 = run_b(es, jp_local, us_yen, jp_mkt_yen, cur_yen_mix)
    BE2['edges_used'] = {'e_paper_P1_VM_full_cagr_diff': e_paper, 'e_vehicle_selected_full_cagr_diff': e_veh}

    # ── F
    log('== F（前向きの模擬・報告のみ）')
    F = None
    if best_cap and best_cap.get('_beta') is not None:
        fee_m = ((fees.get(pick['id']) or {}).get('fee_incl_tax_pct') or 0.0) / 1200
        F = forward(CUR, SPX, jkp_mkt_yen, act[best_cap['leg']], best_cap['_beta'], best_cap['_alpha_m'], fee_m)
        F['vehicle'] = pick['id']
        F['note'] = 'S0 は歴史の平均のまま。S1 は日本の市場・今の ETF 側・S&P500 の平均を全部 S&P500 円の平均にそろえ、袖の上乗せ＝紙の上乗せの平均×0.5×器の β − 器の費用。S2 は上乗せ0（分散だけ）'

    # ── まとめ
    for r in P2:
        cp = r.get('capture')
        if isinstance(cp, dict):
            cp.pop('_alpha_m', None); cp.pop('_beta', None)
    tested = P1 + X1 + X2 + P2
    out.update({
        'benchmark': {'P1_X1': 'French Japan Mkt（Mkt-RF＋RF・米ドル）→ 円（DEXJPUS 月末）', 'X2': 'JKP 日本 mkt vw（超過）＋French RF → 円',
                      'P2': 'MSCI Japan gross（円）・照合に 1306 の基準価額＋分配金（TOPIX）', 'P3': '今の ETF 側（NASDAQ100 75 : SMH 25・円）と S&P500（円）'},
        'sanity': san, 'jkp_side_check_train_only': side_check,
        'families': {'P1': [r['id'] for r in P1], 'X1': [r['id'] for r in X1], 'X2': [r['id'] for r in X2], 'P2': [r['id'] for r in P2]},
        'tested': tested, 'n_tested': len(tested), 'n_graded_non_report': len(P1) + len(X1) + len(X2),
        'grade_counts': {f: {g: sum(1 for r in rows if r.get('grade') == g) for g in ('S', 'A', 'B', 'C')} for f, rows in (('P1', P1), ('X1', X1), ('X2', X2), ('P2', P2))},
        'investor_P3': P3, 'investor_P3_common_windows': P3_common, 'investor_post_hoc': post, 'break_even_BE1': BE1, 'base_rates_BE2': BE2, 'forward_F': F,
        'yields_assumed': YLD, 'deviations': DEVIATIONS, 'log_tail': LOG[-80:], 'runtime_sec': round(time.time() - t0, 1)})
    out['summary_ja'], out['caveats'] = summarize(out)
    for ln in out['summary_ja']:
        log(' ', ln)
    p = M.save(OUT_NAME, out)
    log('saved', p, os.path.getsize(p))


def summarize(o):
    T = {r['id']: r for r in o['tested']}
    g = lambda i, k, f='ex_ann': ((T[i].get(k) or {}).get(f))
    P3 = o['investor_P3']
    by = lambda jn: P3[jn]['by_years'].get(20) or P3[jn]['by_years'].get('20')
    d20 = lambda jn, x='x20', tx='T0': (by(jn)[tx]['by_x'][x]['vs_current'] or {})
    B1, B2, F = o['break_even_BE1'], o['base_rates_BE2'], o['forward_F'] or {}
    cap = lambda i: (T[i].get('capture') or {})
    pk = (o['forward_registration_request'].get('selected') or {}).get('id')
    post = o['investor_post_hoc']
    lines = [
        f"主の族 P1（日本の大型株＝French の ME5 の角・円・相手は日本の時価加重の市場）: 割安＋質（P1_VQ）が B＝訓練 +{g('P1_VQ','train')}%/年 t{g('P1_VQ','train','t')}・2007〜 +{g('P1_VQ','hold')}%/年 t{g('P1_VQ','hold','t')}（費用後も正・統計は弱い）。"
        f"割安＋勢い（P1_VM）は訓練 t{g('P1_VM','train','t')} で C（2007〜 +{g('P1_VM','hold')}%/年 t{g('P1_VM','hold','t')}）、割安＋質＋勢いも C。A・S は無し。",
        f"再現（X2・JKP 日本 vw・円）: 割安＋勢い X2_VM は S（訓練 +{g('X2_VM','train')} t{g('X2_VM','train','t')}・2007〜2025 +{g('X2_VM','hold')} t{g('X2_VM','hold','t')}・全期間 t{g('X2_VM','full','t')}・先進国21/21で正）＝mw_japan の S を円でも確認。"
        f"配当利回り X2_DIV は 2007〜 +{g('X2_DIV','hold')}%/年 t{g('X2_DIV','hold','t')} と強いが訓練 t{g('X2_DIV','train','t')} で C（mw_japan の上限なし vw 版と同じ）。",
        f"器（報告のみ・構造的に C）: 東証の高配当ETF は紙の配当の上乗せに強く載る（1489 β{cap('1489.T').get('one_factor',{}).get('beta')}・載り{cap('1489.T').get('capture_ratio')}／1651 β{cap('1651.T').get('one_factor',{}).get('beta')}・載り{cap('1651.T').get('capture_ratio')}）が、"
        f"古い器は取れていない（1698 載り{cap('1698.T').get('capture_ratio')}・1478 {cap('1478.T').get('capture_ratio')}）。MSCI Japan 比: 1489 +{g('1489.T','full')}%/年 t{g('1489.T','full','t')}（2017〜）・1651 +{g('1651.T','full')} t{g('1651.T','full','t')}・1698 {g('1698.T','full')}（2010〜）・MSCI 高配当指数 2001〜 +{g('MSCI_JP_HDY','full')} t{g('MSCI_JP_HDY','full','t')}（公表後 +{(T['MSCI_JP_HDY'].get('post_launch') or {}).get('ex_ann')}）。米国外の器 PXF の載り16%よりずっと良い。",
        f"PBR 改革の後（2023-04〜・報告のみ）: 紙の P1_VM +{g('P1_VM','fresh_2023_04')}%/年 t{g('P1_VM','fresh_2023_04','t')}・配当 X2_DIV +{g('X2_DIV','fresh_2023_04')} t{g('X2_DIV','fresh_2023_04','t')}・1651 +{g('1651.T','fresh_2023_04')} t{g('1651.T','fresh_2023_04','t')}・1577 +{g('1577.T','fresh_2023_04')} t{g('1577.T','fresh_2023_04','t')}（40か月だけ）。",
        f"円の毎月積立（20年・ETF 側の20%を日本へ・NISA）: 今の ETF 側（NASDAQ100 75 : SMH 25）に対して、日本の市場の袖は勝率 {d20('J0_MKT_FR').get('win_rate')}（最終資産の比の中央 {(d20('J0_MKT_FR').get('dist') or {}).get('median')}・最悪 {d20('J0_MKT_FR').get('worst')}）、"
        f"大型の割安＋勢いの紙 {d20('J1_P1VM').get('win_rate')}（中央 {(d20('J1_P1VM').get('dist') or {}).get('median')}）、配当の紙 {d20('J2_DIV').get('win_rate')}（中央 {(d20('J2_DIV').get('dist') or {}).get('median')}・勝ったのは起点1989〜1996年だけ）、"
        f"1489 の載りで作った器もどき {d20('J3_CAPT').get('win_rate')}（中央 {(d20('J3_CAPT').get('dist') or {}).get('median')}）、MSCI 高配当指数 {d20('J4_HDY_IDX').get('win_rate')}（1997〜2006年起点・中央 {(d20('J4_HDY_IDX').get('dist') or {}).get('median')}）。10%・30%でも向きは同じ。課税口座（T1・T2）でもほぼ同じ。",
        f"事後: 実在の 1698 を20%入れた10年の積立は今の側に {((post['real_vehicles_10y_x20_T0']['1698.T']['1698.T']['x20_vs_current'] or {}).get('windows'))}窓すべて負け（中央 {(((post['real_vehicles_10y_x20_T0']['1698.T']['1698.T']['x20_vs_current'] or {}).get('dist') or {}).get('median'))}）。"
        f"ETF 側が S&P500 だった場合でも、日本20%を足すと配当の紙以外は20年窓で全敗（配当の紙は勝率 {(post['sp500_side_plus_japan20_vs_sp500_20y_T0']['J2_DIV'] or {}).get('win_rate')}）。",
        f"損益分岐: 20年の窓ごとに今の側と並ぶには、日本の市場の袖に年 +{(B1['J0_MKT_FR']['vs_current']['g_star_pct_per_year'] or {}).get('median')}%（中央）、配当の紙でも +{(B1['J2_DIV']['vs_current']['g_star_pct_per_year'] or {}).get('median')}% の上乗せがさらに要った。"
        f"日本 − 米国（円）の20年の差: 1975〜 の French では日本が勝った窓 {B2['French_1975_monthly']['share_gap_ge_minus_e']['0']}（中央 {B2['French_1975_monthly']['gap_pct_dist']['median']}%/年）、"
        f"JST 1886〜2020 では {B2['JST_annual_1886_2020']['share_gap_ge_minus_e']['0']}（中央 +{B2['JST_annual_1886_2020']['gap_pct_dist']['median']}）＝長い歴史では五分五分、最近50年は米国の一方勝ち。日本の市場 − 今の ETF 側は 1985〜 の全窓で負（中央 {B2['Japan_mkt_minus_current_side_1985']['gap_pct_dist']['median']}%/年）。",
        f"前向きの模擬（1489 の載り）: 歴史の平均のまま（S0）なら20%の日本が勝つ確率 {F.get('scenarios',{}).get('S0',{}).get('x20',{}).get('p_win')}。"
        f"米国テックと日本の期待を同じと置くと（S1: 紙の上乗せの半分×β）{F.get('scenarios',{}).get('S1',{}).get('x20',{}).get('p_win')}、上乗せ0の分散だけ（S2）でも {F.get('scenarios',{}).get('S2',{}).get('x20',{}).get('p_win')}＝答えは『米国テックの上乗せが続くか』の仮定でほぼ決まる。",
        f"前向きの登録（規則で選択）: {pk}（1306＝TOPIX の基準価額比・2026-10〜）と紙の P1_VM。mw_forward への統合は親に委ねた。道具の不具合: mw_common.yahoo は東証銘柄の月を1か月前にずらす（この道具の中だけ直した）。"]
    cav = ['2007年以降の格付けで A・S は無い（S は既知の結果の円での再現だけ）。紙の上乗せはこの投資家の円の積立の結果をほぼ動かさず、結果を決めたのは日本の市場と米国テックの差（年約8%）',
           '東証の高配当ETF の載りの良さ（1489・1651）は 2017 年以降の約9年だけの推定で、β>1 は集中した銘柄数（40〜50社）のせい。後ろへ延ばした器もどき J3 は後知恵を含む',
           '1990〜2026 は日本のバブル天井の直後から始まる窓で、日本に最も不利な時代。JST の長い歴史（1886〜2020）では日本と米国は五分五分',
           '前向きの模擬の勝つ確率は平均の置き方でほぼ決まる（19%〜79%）。算術平均をそろえる置き方は揺れの小さい側に有利（S3 事後で確認: 70%）']
    return lines, cav


if __name__ == '__main__':
    main()
