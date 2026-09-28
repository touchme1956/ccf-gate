#!/usr/bin/env python3
"""night/mw_common.py — 『市場に勝てる歴史検証』(mw_*) の共通部品（読むだけ・門の判定には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて」。
各角度の道具 night/mw_<角度>.py はこの部品を使い、合否は out/mw_prereg.json の線で裁く（線は結果を見て動かさない）。

約束
- 月次リターンは小数（0.01 = 1%）、キーは yyyymm の int。日次は yyyymmdd の int。
- French / JKP の数字は CRSP 由来＝**上場廃止した会社も入っている**（生き残りだけの偏りが無い）。
- JKP のリターンは**無リスク金利を引いた値（超過）**。French の Mkt-RF も超過。比べるときは同じ基準どうしで。
  （2026-09-28 検算: JKP mkt 8.86%/年・French Mkt-RF 8.30%/年・RF 3.24%/年 → JKP は超過で確定）
- 相手（市場）は**上限なしの時価加重**＝French の Mkt（S&P500 に近い）。JKP の vw_cap 市場は最大級の会社の重みを
  NYSE 80%点で抑える＝2007年以降の巨大テック時代に弱い相手だった（docs/CLAUDE_ARCHIVE の longonly 節）。
- JKP の weighting は 'vw'（上限なしの時価加重＝米国では French Mkt とほぼ同じ: 全期間 −0.03%/年・2007〜 −0.41%/年）・
  'vw_cap'・'ew' がある。**買いだけの三分位を純粋な市場と比べるときは 'vw'**。地域: 'usa','jpn',…(ISO3)・
  'developed','emerging','frontier','world','world_ex_us'。
- キャッシュは out/_mw_cache/（gitignore）。
"""
import csv, io, json, math, os, statistics as S, time, urllib.request, zipfile, datetime, hashlib

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, 'out', '_mw_cache')
UA = {'User-Agent': 'Mozilla/5.0 (ccf-gate research; contact via github touchme1956/ccf-gate)'}
TRAIN_END, HOLD_START, RECENT_START = 200612, 200701, 201307
FR = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{}_CSV.zip'
JKP = 'https://jkpfactors-data.s3.amazonaws.com/public/{sub}%5B{r}%5D_%5B{k}%5D_%5B{f}%5D_%5B{w}%5D.zip'


# ───────────────────────── 取得 ─────────────────────────
def get(url, name=None, max_age_days=30, tries=5):
    """URL を取得してキャッシュする（bytes を返す）。失敗は 2,4,8,16 秒あけて再試行"""
    os.makedirs(CACHE, exist_ok=True)
    name = name or hashlib.sha1(url.encode()).hexdigest()[:16] + '_' + url.rstrip('/').split('/')[-1][-60:].replace('%', '_').replace('?', '_').replace('&', '_')
    p = os.path.join(CACHE, name)
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < max_age_days * 86400 and os.path.getsize(p) > 0:
        return open(p, 'rb').read()
    err = None
    for i in range(tries):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180).read()
            tmp = f'{p}.{os.getpid()}.tmp'
            open(tmp, 'wb').write(b)
            os.replace(tmp, p)  # 原子的に置く（並行して読む道具が書きかけを掴まないように）
            return b
        except Exception as e:  # noqa
            err = e
            time.sleep(2 ** (i + 1))
    raise RuntimeError(f'取得失敗 {url}: {err}')


def _num(x):
    x = x.strip()
    if x == '':
        return None
    try:
        v = float(x)
    except ValueError:
        return None
    return None if v <= -99.99 or v == -999 else v


def french_tables(name):
    """French の CSV zip を全表まとめて読む → {表題: {'cols': [...], 'freq': 'monthly'|'annual'|'daily', 'data': {日付int: [値(%)…]}}}
    値は**百分率のまま**（French の原本どおり）。欠測（-99.99 / -999）は None。"""
    b = get(FR.format(name), name=f'fr_{name}.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    txt = z.read(z.namelist()[0]).decode('latin-1')
    tables, title, cols, cur = {}, None, None, None
    last_text = ''
    for raw in txt.splitlines():
        line = raw.rstrip()
        cells = [c.strip() for c in line.split(',')]
        first = cells[0]
        if first.isdigit() and cols is not None and len(first) in (4, 6, 8):
            freq = {4: 'annual', 6: 'monthly', 8: 'daily'}[len(first)]
            if cur is None:
                key = (title or last_text or 'table').strip()
                k2, i = key, 2
                while k2 in tables:
                    k2 = f'{key} #{i}'; i += 1
                cur = tables[k2] = {'cols': cols, 'freq': freq, 'data': {}}
            cur['data'][int(first)] = [_num(c) for c in cells[1:1 + len(cols)]]
            continue
        if first == '' and len(cells) > 1 and any(c for c in cells[1:]) and not any(c.replace('.', '').replace('-', '').isdigit() for c in cells[1:3]):
            cols = [c for c in cells[1:]]
            while cols and cols[-1] == '':
                cols.pop()
            title = last_text
            cur = None
            continue
        if line.strip() == '':
            cur = None if cur is not None else cur
            continue
        if not first.isdigit():
            last_text = line.strip().strip(',')
            cur = None
    return tables


def french_series(name, want='Value Weight', freq='monthly'):
    """表題に want を含む最初の表（freq 一致）を {列名: {日付: 小数リターン}} で返す"""
    for t, v in french_tables(name).items():
        if want.lower() in t.lower() and v['freq'] == freq:
            out = {c: {} for c in v['cols']}
            for d, row in v['data'].items():
                for c, x in zip(v['cols'], row):
                    if x is not None:
                        out[c][d] = x / 100
            return out
    raise KeyError(f'{name}: 「{want}」の {freq} 表が無い。表題一覧: {list(french_tables(name))}')


def ff_factors(freq='monthly'):
    """French 3因子の元ファイル → {'mkt': 総リターン, 'mktrf': 超過, 'rf': 無リスク, 'smb', 'hml'}（小数）"""
    name = 'F-F_Research_Data_Factors' + ('_daily' if freq == 'daily' else '')
    for t, v in french_tables(name).items():
        if v['freq'] == freq:
            cols = [c.lower().replace('-', '') for c in v['cols']]
            out = {c: {} for c in cols}
            for d, row in v['data'].items():
                for c, x in zip(cols, row):
                    if x is not None:
                        out[c][d] = x / 100
            out['mkt'] = {d: out['mktrf'][d] + out['rf'][d] for d in out['mktrf'] if d in out['rf']}
            return out
    raise KeyError(name)


def jkp_rows(region, key, kind='factor', weighting='vw_cap', freq='monthly'):
    sub = 'portfolios/' if kind == 'portfolios' else ''
    b = get(JKP.format(sub=sub, r=region, k=key, f=freq, w=weighting), name=f'jkp_{kind}_{region}_{key}_{weighting}_{freq}.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    return list(csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())))


def _ym(s):
    return int(s[:4]) * 100 + int(s[5:7])


def jkp_factor(region, key, weighting='vw_cap'):
    """JKP の因子（買い−売り・符号は予言の向きに揃え済み・超過）→ {yyyymm: 小数}"""
    return {_ym(x['date']): float(x['ret']) for x in jkp_rows(region, key, 'factor', weighting) if x['ret'] not in ('', 'NA', 'na')}


def jkp_mkt(region, weighting='vw_cap'):
    return jkp_factor(region, 'mkt', weighting)


def jkp_portfolios(region, key, weighting='vw_cap'):
    """JKP の三分位ポートフォリオ（超過）→ {'1.0': {...}, '2.0': {...}, '3.0': {...}}。
    どちらが『良い側』かは jkp_good_side で機械的に決める（手で選ばない）"""
    d = {}
    for x in jkp_rows(region, key, 'portfolios', weighting):
        if x['ret'] in ('', 'NA', 'na'):
            continue
        d.setdefault(x['pf'], {})[_ym(x['date'])] = float(x['ret'])
    return d


def jkp_good_side(region, key, weighting='vw_cap', upto=None):
    """良い側 = (第3−第1) と JKP の符号つき因子の相関の符号。upto(yyyymm) を渡すとその月までのデータだけで決める（後知恵を避ける）"""
    p = jkp_portfolios(region, key, weighting)
    f = jkp_factor(region, key, weighting)
    ms = sorted(m for m in set(p.get('3.0', {})) & set(p.get('1.0', {})) & set(f) if upto is None or m <= upto)
    if len(ms) < 24:
        return None, p
    c = corr([p['3.0'][m] - p['1.0'][m] for m in ms], [f[m] for m in ms])
    return ('3.0' if c > 0 else '1.0'), p


def yahoo(ticker, interval='1mo', start=None):
    """Yahoo の調整後終値（配当込み）からリターン → {yyyymm or yyyymmdd: 小数}。interval='1d' なら日次"""
    import urllib.parse
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?period1={start or 0}&period2={int(time.time())}&interval={interval}&events=div%2Csplit'
    j = json.loads(get(u, name=f'yh_{ticker.replace("^", "IDX_").replace("=", "_")}_{interval}.json', max_age_days=3))
    r = j['chart']['result'][0]
    ts = r['timestamp']
    adj = r['indicators'].get('adjclose', [{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    px = {}
    for t, a in zip(ts, adj):
        if a is None:
            continue
        d = datetime.datetime.utcfromtimestamp(t)
        k = d.year * 100 + d.month if interval == '1mo' else d.year * 10000 + d.month * 100 + d.day
        px[k] = a
    if interval == '1mo':
        # 2026-09-28 mw_forward の点検で判明: 月足の最後の本は『まだ終わっていない今月』（途中の値）。
        # 途中の月を1か月として混ぜないよう、今月以降の本を落とす
        now = datetime.datetime.utcnow()
        px = {k: v for k, v in px.items() if k < now.year * 100 + now.month}
    ks = sorted(px)
    return {k: px[k] / px[p] - 1 for p, k in zip(ks, ks[1:])}


# ───────────────────────── 統計 ─────────────────────────
def corr(a, b):
    ma, mb = S.mean(a), S.mean(b)
    va = sum((x - ma) ** 2 for x in a); vb = sum((y - mb) ** 2 for y in b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb) if va and vb else 0.0


def nw_t(x, lag=12):
    """Newey-West（Bartlett）の t値。重なりや自己相関があっても過大にならないように"""
    n = len(x)
    if n < 24:
        return None
    m = S.mean(x); e = [v - m for v in x]
    g0 = sum(v * v for v in e) / n
    s = g0
    for L in range(1, min(lag, n - 1) + 1):
        gl = sum(e[i] * e[i - L] for i in range(L, n)) / n
        s += 2 * (1 - L / (lag + 1)) * gl
    return m / math.sqrt(s / n) if s > 0 else None


def p_two(t):
    return math.erfc(abs(t) / math.sqrt(2)) if t is not None else None


def window(d, a=None, z=None):
    return {k: v for k, v in d.items() if (a is None or k >= a) and (z is None or k <= z)}


def cagr(r, per_year=12):
    x = list(r.values()) if isinstance(r, dict) else list(r)
    if not x:
        return None
    g = math.fsum(math.log1p(v) for v in x)
    return math.exp(g * per_year / len(x)) - 1


def maxdd(r):
    w, pk, dd = 1.0, 1.0, 0.0
    for k in sorted(r):
        w *= 1 + r[k]; pk = max(pk, w); dd = min(dd, w / pk - 1)
    return dd


def excess_stats(s, b, a=None, z=None, per_year=12, lag=12):
    """s・b は同じ基準（両方総リターン or 両方超過）。差の算術平均×12・NW t・幾何の年率差・追従のぶれ・β・勝ち年率"""
    ks = sorted(k for k in set(s) & set(b) if (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < max(24, per_year * 2):
        return None
    ex = [s[k] - b[k] for k in ks]
    sv, bv = [s[k] for k in ks], [b[k] for k in ks]
    te = S.stdev(ex) * math.sqrt(per_year)
    vb = S.pvariance(bv)
    beta = sum((x - S.mean(sv)) * (y - S.mean(bv)) for x, y in zip(sv, bv)) / len(ks) / vb if vb else None
    t = nw_t(ex, lag)
    g_s, g_b = cagr(sv, per_year), cagr(bv, per_year)
    return {'from': ks[0], 'to': ks[-1], 'years': round(len(ks) / per_year, 1),
            'ex_ann': round(S.mean(ex) * per_year * 100, 2), 't': round(t, 2) if t is not None else None,
            'p': round(p_two(t), 4) if t is not None else None,
            'cagr_s': round(g_s * 100, 2), 'cagr_b': round(g_b * 100, 2), 'cagr_diff': round((g_s - g_b) * 100, 2),
            'te': round(te * 100, 2), 'ir': round(S.mean(ex) * per_year / te, 2) if te else None,
            'beta': round(beta, 2) if beta is not None else None,
            'vol_s': round(S.stdev(sv) * math.sqrt(per_year) * 100, 1), 'vol_b': round(S.stdev(bv) * math.sqrt(per_year) * 100, 1)}


def sharpe(r, rf, a=None, z=None, per_year=12):
    ks = sorted(k for k in set(r) & set(rf) if (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 24:
        return None
    x = [r[k] - rf[k] for k in ks]
    sd = S.stdev(x)
    return round(S.mean(x) / sd * math.sqrt(per_year), 3) if sd else None


def rolling(s, b, years=20, start_month=7, per_year=12):
    """転がる窓（毎年 start_month 月起点・一括投資）の幾何の年率差 → 勝率・中央・最悪・最良"""
    ks = sorted(set(s) & set(b))
    if not ks:
        return None
    out = []
    y0 = ks[0] // 100 if per_year == 12 else ks[0] // 10000
    last = ks[-1]
    for y in range(y0, 2100):
        if per_year == 12:
            a, z = y * 100 + start_month, (y + years) * 100 + start_month - 1 if start_month > 1 else (y + years - 1) * 100 + 12
        else:
            a, z = y * 10000 + start_month * 100, (y + years) * 10000 + start_month * 100 - 1
        if z > last:
            break
        w = [k for k in ks if a <= k <= z]
        if len(w) < years * per_year * 0.97:
            continue
        gs = math.exp(math.fsum(math.log1p(s[k]) for k in w) / years) - 1
        gb = math.exp(math.fsum(math.log1p(b[k]) for k in w) / years) - 1
        out.append((y, round((gs - gb) * 100, 2)))
    if not out:
        return None
    v = sorted(c for _, c in out)
    return {'windows': len(out), 'wins': sum(1 for _, c in out if c > 0), 'win_rate': round(sum(1 for _, c in out if c > 0) / len(out), 3),
            'median': v[len(v) // 2], 'worst': min(out, key=lambda x: x[1]), 'best': max(out, key=lambda x: x[1])}


def dca(s, b, years=20, step=12):
    """毎月同額を years 年積み立てた最終額の比（s ÷ b）の分布。step か月ごとに起点をずらす"""
    ks = sorted(set(s) & set(b))
    n = years * 12
    out = []
    for i in range(0, len(ks) - n + 1, step):
        w = ks[i:i + n]
        ws = wb = 0.0
        for k in w:
            ws = (ws + 1) * (1 + s[k]); wb = (wb + 1) * (1 + b[k])
        out.append((w[0], round(ws / wb, 3)))
    if not out:
        return None
    v = sorted(r for _, r in out)
    return {'windows': len(out), 'win_rate': round(sum(1 for r in v if r > 1) / len(v), 3), 'median_ratio': v[len(v) // 2],
            'worst': min(out, key=lambda x: x[1]), 'best': max(out, key=lambda x: x[1])}


def holm(pvals):
    """Holm の段階的補正。{名前: p} → {名前: 補正後 p}"""
    items = sorted((p, k) for k, p in pvals.items() if p is not None)
    m, out, run = len(items), {}, 0.0
    for i, (p, k) in enumerate(items):
        run = max(run, min(1.0, (m - i) * p))
        out[k] = round(run, 4)
    return out


def apply_cost(r, annual_oneway_turnover, cost_per_unit=0.001, per_year=12):
    """売買費用を月割りで引く。cost_per_unit = 片道売買 100% あたりの費用（大型株 0.10%・中小型 0.30% を既定の目安）"""
    c = annual_oneway_turnover * cost_per_unit / per_year
    return {k: v - c for k, v in r.items()}


def lever_daily(r, L, rf, spread=0.005, fee=0.009, days=252):
    """日次で L 倍に保つ（レバレッジETFの型）。借入は (L−1)×(RF+spread)、信託報酬 fee。rf は日次の小数 {日付: 値}"""
    out = {}
    for k, v in r.items():
        f = rf.get(k, 0.0)
        out[k] = L * v - (L - 1) * (f + spread / days) - fee / days
    return out


def to_monthly(daily):
    """日次 {yyyymmdd: r} → 月次 {yyyymm: r}"""
    m = {}
    for k in sorted(daily):
        ym = k // 100
        m[ym] = (1 + m.get(ym, 0.0)) * (1 + daily[k]) - 1
    return m


# ───────────────────────── 判定 ─────────────────────────
PRE = os.path.join(BASE, 'out', 'mw_prereg.json')


def grade(full, train, hold, roll20, cost_hold=None, repl=None, family_holm_p=None, sharpe_pair=None, leveraged_or_timing=False):
    """out/mw_prereg.json の線（C1〜C8）をそのまま当てる。欠けた入力は不合格側に倒す（空欄を合格にしない）。
    full/train/hold/cost_hold = excess_stats の戻り値、roll20 = rolling の戻り値、
    repl = {'regions': n, 'positive': k}、family_holm_p = 角度の族の中での Holm 補正後 p（保有期間）、
    sharpe_pair = {'train': (s, b), 'hold': (s, b)}"""
    c = {}
    c['C1_train'] = bool(train and train['ex_ann'] > 0 and (train['t'] or 0) >= 2.0)
    c['C2_hold_sign'] = bool(hold and hold['ex_ann'] > 0 and hold['cagr_diff'] > 0)
    c['C3_hold_t'] = bool(hold and (hold['t'] or 0) >= 1.65)
    c['C4_roll20'] = bool(roll20 and roll20['win_rate'] >= 0.8)
    if repl and repl.get('regions'):
        c['C5_repl'] = repl['positive'] / repl['regions'] >= 2 / 3
    else:
        c['C5_repl'] = None
    ch = cost_hold if cost_hold is not None else None
    c['C6_net_cost'] = bool(ch and ch['ex_ann'] > 0 and ch['cagr_diff'] > 0)
    c['C7_multi'] = bool((full and (full['t'] or 0) >= 3.0) or (family_holm_p is not None and family_holm_p < 0.05))
    if leveraged_or_timing:
        sp = sharpe_pair or {}
        c['C8_sharpe'] = bool(sp.get('train') and sp.get('hold') and None not in sp['train'] + sp['hold']
                              and sp['train'][0] > sp['train'][1] and sp['hold'][0] > sp['hold'][1])
    else:
        c['C8_sharpe'] = None
    ok = lambda k: c[k] is True
    na_or = lambda k: c[k] is None or c[k] is True
    base = ok('C1_train') and ok('C2_hold_sign') and ok('C6_net_cost') and na_or('C8_sharpe')
    if base and ok('C3_hold_t') and ok('C4_roll20') and ok('C7_multi') and na_or('C5_repl'):
        g = 'S'
    elif base and ok('C4_roll20') and ok('C7_multi') and (ok('C3_hold_t') or ok('C5_repl')):
        g = 'A'
    elif base:
        g = 'B'
    else:
        g = 'C'
    return g, c


def save(name, obj):
    obj = dict(obj)
    obj.setdefault('generated', datetime.date.today().isoformat())
    p = os.path.join(BASE, 'out', name)
    json.dump(obj, open(p, 'w'), ensure_ascii=False, indent=1)
    return p


if __name__ == '__main__':
    ff = ff_factors()
    m = ff['mkt']
    print('French Mkt', min(m), max(m), 'CAGR', round(cagr(m) * 100, 2))
    print('2007〜 CAGR', round(cagr(window(m, HOLD_START)) * 100, 2))
