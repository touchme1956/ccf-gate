#!/usr/bin/env python3
"""night/mw_best_ideas_13f.py — 角度 best_ideas_13f（読むだけ・門の判定には不使用）

問い: 機関投資家（13F 提出者）の中で『いちばん自信のある銘柄（best idea）』＝自分の比重が市場の比重を
      最も上回っている銘柄を、提出が公開された翌月から写して持つと、純粋な時価加重の米国市場（French Mkt）に勝つか。
      Cohen, Polk & Silli (2010)『Best Ideas』の発見期（1991〜2005・投信）の後の、公表後の検証（2013〜2026）。

事前登録: out/mw_best_ideas_13f_prereg.json（測る前にコミット）。線は out/mw_prereg.json（C1〜C8）を
mw_common.grade でそのまま当てる。★この角度には訓練期間（〜2006-12）のデータが無い（SEC の 13F 構造化データは
2013Q2 から）ので C1 は測れず、全戦略が構造的に C（格の天井）。価値は『公表後に効いているか』の正直な読み。

株価は Yahoo（上場廃止した社は消える＝生き残りの偏り）。未観測の社は
  O  = 観測できる社だけで按分（生き残りの偏りそのまま・楽観側）
  P30 = 観測できない月の最初に −30%、その後は 0%（悲観側）
  P100 = 同じく −100%（最悪側）
の三本で囲み、0 で埋めない（絶対のルール7）。
道 Q（頑健性）: 13F の四半期末の暗黙の株価（全提出者の中央値・配当なし）で同じ比重を持ち、French の配当なしの市場と比べる
（上場廃止した社も機関が持っていれば価格がある＝生き残りの偏りが小さい）。

段
  --fetch   : SEC 13F データセット（四半期 zip）と FTD（CUSIP→記号の当時の対応）を取る → out/_mw_cache/bi13f/
  --parse   : 各四半期を読み、運用者ごとの候補（比重の傾き上位5・比重上位5）と集計の市場を作る → period_*.json
  --map     : 候補の CUSIP を FTD（当時の記号）と OpenFIGI（現在の記号・証券の種類）で記号へ
  --fetch-yh: 候補の記号の Yahoo 月次を取る（価格の照合つき）
  --parse-q : 13F の四半期末の暗黙の株価と分割の検出用の持ち手の株数 → qpx_*.json（道 Q）
  --coverage: 対応の被覆だけ数える（戦略と市場の比較は計算しない）
  (既定)    : 計算して out/mw_best_ideas_13f.json を書く
"""
import csv, datetime, gzip, io, json, math, os, re, subprocess, sys, time, urllib.error, urllib.request, zipfile
import statistics as S
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402

csv.field_size_limit(1 << 30)
BASE = M.BASE
C = os.path.join(M.CACHE, 'bi13f')
YHD = os.path.join(C, 'yh')
IE_YH = os.path.join(M.CACHE, 'ie_yh')      # index_events の Yahoo キャッシュ（同じ形式・読むだけで再利用）
SEC_UA = {'User-Agent': 'ccf-gate research fortis5280@gmail.com', 'Accept-Encoding': 'gzip'}
PAGE_13F = 'https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets'
PAGE_FTD = 'https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data'
PREREG = 'mw_best_ideas_13f_prereg.json'
OUT = 'mw_best_ideas_13f.json'
END = 202608                      # French の終わり
FIRST_P, LAST_P = 201306, 202603  # 報告期間（四半期末）の最初と最後（201303 は XML 化の前で 13F-HR が46件しか無い）

# ── 事前登録した定数（out/mw_best_ideas_13f_prereg.json と同じ） ──
NMIN, NMAX = 10, 500              # 運用者の株の銘柄数（能動的な運用者の近似）
ETF_SHARE_MAX = 0.20              # ETF 等の比重がこれを超える運用者は除く
NCAND = 5                         # 候補の数（傾き上位）
LARGE_N, INVEST_N = 500, 1000     # 大型株 = 集計の保有額の上位500、投資可能 = 上位1000
TOPK = 20                         # D: best idea に選んだ運用者の数が多い大型株 上位20
PX_TOL = 0.15                     # 13F の暗黙の株価と Yahoo の当時の株価の照合の許容
SPIKE = 3.0                       # 月 +300% 超はデータの誤り → その月から未観測
MISS_P30, MISS_P100 = -0.30, -1.00
COST_SMALL, COST_LARGE = 0.003, 0.001

PASSIVE_RE = re.compile(r'VANGUARD|BLACKROCK|STATE STREET|GEODE|DIMENSIONAL|NORTHERN TRUST|SCHWAB|ISHARES|SPDR|WISDOMTREE|'
                        r'PROSHARE|DIREXION|FIRST TRUST|VAN ECK|VANECK|GLOBAL X|PARAMETRIC|RAFFERTY|\bINDEX\b', re.I)
ETF_RE = re.compile(r'\b(ETF|ETFS|ETN|ETNS|EXCHANGE TRADED|EXCH TRADED|EXCHANGE-TRADED|ISHARES|SPDR|PROSHARES|POWERSHARES|DIREXION|'
                    r'SELECT SECTOR|MARKET VECTORS|VANECK|GLOBAL X|WISDOMTREE TR|SCHWAB STRATEGIC|INDEX FD|INDEX FDS|INDEX FUND|'
                    r'INDEX FUNDS|VANGUARD|INVESCO QQQ|INVESCO DB|FIRST TR|ALPS ETF|PACER FDS|ARK ETF|TR UNIT|UNIT SER|IPATH|'
                    r'CURRENCYSHARES|GRAYSCALE|FUND|FUNDS|FD|FDS)\b', re.I)
NONCOMMON_RE = re.compile(r'\b(PFD|PREF|PREFERRED|PRFD|NOTE|NOTES|BOND|BONDS|DEBT|DEBENTURE|DEBENTURES|DBCV|SDCV|SR NT|'
                          r'WT|WTS|WARRANT|WARRANTS|RIGHT|RIGHTS|RTS|CALL|PUT|OPTION|OPTIONS)\b', re.I)
MON = {m: i + 1 for i, m in enumerate(['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'])}


# ───────────────────────── 月の算術 ─────────────────────────
def madd(m, k):
    y, mo = divmod(m, 100)
    t = y * 12 + (mo - 1) + k
    return (t // 12) * 100 + t % 12 + 1


def months(a, z):
    out, m = [], a
    while m <= z:
        out.append(m); m = madd(m, 1)
    return out


def periods():
    return [p for p in months(FIRST_P, LAST_P) if p % 100 in (3, 6, 9, 12)]


def d8(s):  # 'DD-MON-YYYY' → yyyymmdd
    d, mo, y = s.split('-')
    return int(y) * 10000 + MON[mo.upper()] * 100 + int(d)


def formation(p):
    """報告期間末 p（yyyymm）→ 期限月 F（提出の締切 45日後を含む月）。F の月末までに提出されたものを使い、F+1〜F+3 を持つ"""
    return madd(p, 2)


def cutoff_date(p):
    """期限月 F の末日の3日前まで（末日の終値で買う前に確実に公開されている提出だけを使う・後知恵を避ける）"""
    f = formation(p)
    nxt = madd(f, 1)
    last = datetime.date(nxt // 100, nxt % 100, 1) - datetime.timedelta(days=4)
    return last.year * 10000 + last.month * 100 + last.day


# ───────────────────────── 取得 ─────────────────────────
def sec_get(url, path, sleep=0.15, tries=5):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return open(path, 'rb').read()
    err = None
    for i in range(tries):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=SEC_UA), timeout=300).read()
            try:
                b = gzip.decompress(b)
            except OSError:
                pass
            if b[:15].lstrip().lower().startswith(b'<!doctype html') and path.endswith('.zip'):
                raise RuntimeError('HTML が返った（404 相当）')
            tmp = f'{path}.{os.getpid()}.tmp'
            open(tmp, 'wb').write(b); os.replace(tmp, path)
            time.sleep(sleep)
            return b
        except Exception as e:  # noqa
            err = e; time.sleep(2 * (i + 1))
    raise RuntimeError(f'SEC 取得失敗 {url}: {err}')


def links(page, name, pat):
    b = sec_get(page, os.path.join(C, name))
    return re.findall(pat, b.decode('utf-8', 'ignore'))


def zip_for_period(p, hrefs):
    """報告期間 p の提出（p+1〜p+2 月）をすべて含むデータセットの zip"""
    f1, f2 = madd(p, 1), madd(p, 2)
    for h in hrefs:
        fn = h.rsplit('/', 1)[-1]
        m = re.match(r'(\d{4})q([1-4])_form13f\.zip', fn)
        if m:
            y, q = int(m.group(1)), int(m.group(2))
            a, z = y * 100 + 3 * q - 2, y * 100 + 3 * q
        else:
            m = re.match(r'(\d{2})([a-z]{3})(\d{4})-(\d{2})([a-z]{3})(\d{4})_form13f\.zip', fn)
            if not m:
                continue
            a = int(m.group(3)) * 100 + MON[m.group(2).upper()]
            z = int(m.group(6)) * 100 + MON[m.group(5).upper()]
        if a <= f1 and f2 <= z:
            return h
    return None


def fetch():
    os.makedirs(C, exist_ok=True)
    hrefs = links(PAGE_13F, 'page_13f.html', r'href="([^"]*form13f\.zip)"')
    for p in periods():
        h = zip_for_period(p, hrefs)
        if not h:
            print('!! 期間', p, 'の zip が無い'); continue
        path = os.path.join(C, h.rsplit('/', 1)[-1])
        sec_get('https://www.sec.gov' + h, path)
        print(p, '→', os.path.basename(path), os.path.getsize(path) // 1_000_000, 'MB')
    ftd = links(PAGE_FTD, 'page_ftd.html', r'href="([^"]*cnsfails(\d{6})[ab]\.zip)"')
    os.makedirs(os.path.join(C, 'ftd'), exist_ok=True)
    n = 0
    for h, ym in ftd:
        if 201212 <= int(ym) <= 202608:
            sec_get('https://www.sec.gov' + h, os.path.join(C, 'ftd', h.rsplit('/', 1)[-1]))
            n += 1
    print('FTD', n, '本')


# ───────────────────────── 13F を読む ─────────────────────────
def tsv(z, name):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, 'utf-8', errors='ignore'), delimiter='\t', quoting=csv.QUOTE_NONE)


def norm_cusip(s):
    s = re.sub(r'[^0-9A-Za-z]', '', s or '').upper()
    return s if len(s) == 9 else None


def read_clean(p, zpath):
    """1四半期の 13F-HR を選び、株の行を読んで単位を揃える（parse_period と parse_q が共有する単一の実装）"""
    z = zipfile.ZipFile(zpath)
    cut = cutoff_date(p)
    pe = p // 100 * 10000 + p % 100 * 100
    cover = {r['ACCESSION_NUMBER']: r for r in tsv(z, 'COVERPAGE.tsv')}
    best = {}   # cik → (filing_date, accession)
    for r in tsv(z, 'SUBMISSION.tsv'):
        if r['SUBMISSIONTYPE'] != '13F-HR':
            continue
        try:
            per, fd = d8(r['PERIODOFREPORT']), d8(r['FILING_DATE'])
        except Exception:  # noqa
            continue
        if per // 100 != pe // 100 or fd > cut:
            continue
        cv = cover.get(r['ACCESSION_NUMBER'], {})
        if cv.get('REPORTTYPE', '').upper() not in ('13F HOLDINGS REPORT', '13F COMBINATION REPORT'):
            continue
        if (cv.get('ISAMENDMENT') or '').upper() == 'Y':
            continue
        cik = int(r['CIK'])
        k = (fd, r['ACCESSION_NUMBER'])
        if cik not in best or k > best[cik]:      # 締切までに出た最後の原本
            best[cik] = k
    acc2cik = {a: c for c, (_, a) in best.items()}
    # 行を読む（株・オプションでない・値>0）
    rows = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))   # acc → cusip → [value_raw, shares]
    etfv = defaultdict(float)                                      # acc → ETF 等の値（raw）
    names = defaultdict(Counter); titles = defaultdict(Counter)
    for r in tsv(z, 'INFOTABLE.tsv'):
        a = r['ACCESSION_NUMBER']
        if a not in acc2cik:
            continue
        if (r.get('SSHPRNAMTTYPE') or '').upper() != 'SH' or (r.get('PUTCALL') or '').strip():
            continue
        cu = norm_cusip(r.get('CUSIP'))
        try:
            v, sh = float(r['VALUE']), float(r['SSHPRNAMT'])
        except Exception:  # noqa
            continue
        if not cu or v <= 0 or sh <= 0:
            continue
        nm, tt = (r.get('NAMEOFISSUER') or '').strip(), (r.get('TITLEOFCLASS') or '').strip()
        if NONCOMMON_RE.search(tt):
            continue
        if ETF_RE.search(nm + ' ' + tt):
            etfv[a] += v
            continue
        x = rows[a][cu]; x[0] += v; x[1] += sh
        names[cu][nm] += 1; titles[cu][tt] += 1
    # 単位の揃え: CUSIP ごとの合意の株価（raw 単位の中央値）と行ごとの 10 のべき
    px = defaultdict(list)
    for a, d in rows.items():
        for cu, (v, sh) in d.items():
            px[cu].append(v / sh)
    cons = {cu: S.median(v) for cu, v in px.items() if len(v) >= 3}
    agg = defaultdict(float); fix = Counter()
    clean = {}; shs = {}
    for a, d in rows.items():
        rs = [math.log10((v / sh) / cons[cu]) for cu, (v, sh) in d.items() if cu in cons and cons[cu] > 0]
        kf = round(S.median(rs)) if rs else 0
        out = {}
        for cu, (v, sh) in d.items():
            if cu in cons and cons[cu] > 0:
                lr = math.log10((v / sh) / cons[cu])
                k = round(lr)
                if abs(lr - k) > 0.25 or abs(k) > 3:
                    if abs(lr) > math.log10(3):
                        fix['row_dropped'] += 1; continue      # 合意の株価と3倍超ずれ、10のべきでも説明できない行
                    k = 0
                if k:
                    fix['row_rescaled'] += 1
                out[cu] = v / 10 ** k
            else:
                if kf:
                    fix['row_rescaled_filing'] += 1
                out[cu] = v / 10 ** kf
            shs[(a, cu)] = sh
        # ETF の値も同じ尺度に（申告単位の比 kf で）
        etfv[a] = etfv[a] / 10 ** kf
        clean[a] = out
        for cu, v in out.items():
            agg[cu] += v
    return {'best': best, 'acc2cik': acc2cik, 'cover': cover, 'clean': clean, 'shs': shs, 'etfv': etfv, 'names': names,
            'titles': titles, 'px': px, 'cons': cons, 'agg': agg, 'fix': fix, 'rows_n': len(rows), 'cut': cut}


def parse_period(p, zpath):
    """1四半期を読む → 運用者の候補と集計の市場（CUSIP 単位）"""
    R = read_clean(p, zpath)
    best, acc2cik, cover, clean, shs, etfv = R['best'], R['acc2cik'], R['cover'], R['clean'], R['shs'], R['etfv']
    names, titles, px, cons, agg, fix, cut = R['names'], R['titles'], R['px'], R['cons'], R['agg'], R['fix'], R['cut']
    tot = sum(agg.values())
    wagg = {cu: v / tot for cu, v in agg.items()}
    rank = {cu: i + 1 for i, cu in enumerate(sorted(agg, key=lambda c: -agg[c]))}
    mult = 1000 if p <= 202209 else 1
    # 運用者
    mgrs = []
    excl = Counter()
    for a, d in clean.items():
        cik = acc2cik[a]
        nm = cover.get(a, {}).get('FILINGMANAGER_NAME', '')
        sv = sum(d.values()); ev = etfv.get(a, 0.0)
        n = len(d)
        if sv <= 0:
            excl['no_stock'] += 1; continue
        why = None
        if PASSIVE_RE.search(nm):
            why = 'passive_name'
        elif n < NMIN:
            why = 'n_lt_10'
        elif n > NMAX:
            why = 'n_gt_500'
        elif ev / (sv + ev) > ETF_SHARE_MAX:
            why = 'etf_share'
        if why:
            excl[why] += 1; continue
        w = {cu: v / sv for cu, v in d.items()}
        tilt = sorted(((w[cu] - wagg[cu], cu) for cu in w), reverse=True)[:NCAND]
        topw = sorted(((w[cu], cu) for cu in w), reverse=True)[:NCAND]
        ipx = lambda cu: round(d[cu] * mult / shs[(a, cu)], 4) if shs.get((a, cu)) else None   # この運用者の暗黙の株価（$）
        mgrs.append({'cik': cik, 'name': nm, 'n': n, 'value_usd': round(sv * mult), 'etf_share': round(ev / (sv + ev), 4),
                     'tilt': [[cu, round(w[cu], 6), round(t, 6), ipx(cu)] for t, cu in tilt],
                     'topw': [[cu, round(ww, 6), None, ipx(cu)] for ww, cu in topw]})
    keep = set(cu for m in mgrs for x in m['tilt'] + m['topw'] for cu in [x[0]]) | {cu for cu, r in rank.items() if r <= INVEST_N}
    sec = {cu: {'agg_usd': round(agg[cu] * mult), 'rank': rank[cu], 'holders': len(px[cu]),
                'px_usd': round(cons[cu] * mult, 4) if cu in cons else None,
                'name': names[cu].most_common(1)[0][0], 'title': titles[cu].most_common(1)[0][0]} for cu in keep}
    return {'period': p, 'formation': formation(p), 'cutoff': cut, 'zip': os.path.basename(zpath), 'unit_mult': mult,
            'n_filings': len(best), 'n_rows_filings': R['rows_n'], 'n_eligible': len(mgrs), 'excluded': dict(excl),
            'fix': dict(fix), 'agg_total_usd': round(tot * mult), 'managers': mgrs, 'sec': sec}


def _parse_one(p):
    hrefs = links(PAGE_13F, 'page_13f.html', r'href="([^"]*form13f\.zip)"')
    outp = os.path.join(C, f'period_{p}.json')
    if os.path.exists(outp):
        return
    h = zip_for_period(p, hrefs)
    t0 = time.time()
    d = parse_period(p, os.path.join(C, h.rsplit('/', 1)[-1]))
    tmp = outp + '.tmp'
    json.dump(d, open(tmp, 'w')); os.replace(tmp, outp)
    aapl = d['sec'].get('037833100', {})
    print(p, 'filings', d['n_filings'], 'eligible', d['n_eligible'], 'excl', d['excluded'], 'fix', d['fix'],
          'AAPL px', aapl.get('px_usd'), 'rank', aapl.get('rank'), f'{time.time() - t0:.0f}s', flush=True)


def parse():
    import multiprocessing as mp
    with mp.Pool(2) as pool:
        pool.map(_parse_one, periods(), chunksize=1)


QCAP = 150                        # 分割の検出に使う持ち手の数の上限（CIK の小さい順・毎期おなじ持ち手が選ばれやすい）


def _parse_q_one(p):
    """13F の四半期末の株価（合意＝提出者の暗黙の株価の中央値）と、分割の検出用の持ち手ごとの株数 → qpx_{p}.json"""
    hrefs = links(PAGE_13F, 'page_13f.html', r'href="([^"]*form13f\.zip)"')
    outp = os.path.join(C, f'qpx_{p}.json')
    if os.path.exists(outp):
        return
    U = set(json.load(open(os.path.join(C, 'universe.json'))))
    h = zip_for_period(p, hrefs)
    t0 = time.time()
    R = read_clean(p, os.path.join(C, h.rsplit('/', 1)[-1]))
    mult = 1000 if p <= 202209 else 1
    ipx = defaultdict(list); holders = defaultdict(dict)
    for a, d in R['clean'].items():
        cik = R['acc2cik'][a]
        for cu, v in d.items():
            if cu not in U:
                continue
            sh = R['shs'].get((a, cu))
            if not sh:
                continue
            ipx[cu].append(v * mult / sh)
            holders[cu][cik] = sh
    out = {}
    for cu, xs in ipx.items():
        hs = holders[cu]
        keep = sorted(hs)[:QCAP]
        out[cu] = [round(S.median(xs), 6), len(xs), {str(c): hs[c] for c in keep}]
    tmp = outp + '.tmp'
    json.dump(out, open(tmp, 'w')); os.replace(tmp, outp)
    print('q', p, len(out), f'{time.time() - t0:.0f}s', flush=True)


def parse_q():
    P = all_periods_data()
    U = set()
    for d in P.values():
        for m in d['managers']:
            U.update(x[0] for x in m['tilt'] + m['topw'])
        U.update(cu for cu, v in d['sec'].items() if v['rank'] <= INVEST_N)
    json.dump(sorted(U), open(os.path.join(C, 'universe.json'), 'w'))
    print('四半期末の株価を取る CUSIP', len(U), flush=True)
    import multiprocessing as mp
    with mp.Pool(2) as pool:
        pool.map(_parse_q_one, periods(), chunksize=1)


def load_period(p):
    return json.load(open(os.path.join(C, f'period_{p}.json')))



# ───────────────────────── CUSIP → 記号 ─────────────────────────
FTD_FUND_RE = re.compile(r'\b(ETF|ETN|ISHARES|SPDR|PROSHARES|POWERSHARES|DIREXION|INDEX FD|INDEX FUND|EXCHANGE TRADED|EXCH TRADED|'
                         r'FUND|FD|FDS)\b', re.I)
NONSTOCK_TYPES = {'ETP', 'Closed-End Fund', 'Open-End Fund', 'Mutual Fund', 'Fund of Funds', 'Unit Inv Tr', 'Preference',
                  'Preferred', 'Right', 'Warrant', 'Equity WRT', 'Index WRT', 'Unit', 'Structured Product', 'SIMPLE'}


def all_periods_data():
    return {p: load_period(p) for p in periods() if os.path.exists(os.path.join(C, f'period_{p}.json'))}


def candidate_cusips(P):
    cs = set()
    for d in P.values():
        for m in d['managers']:
            cs.update(x[0] for x in m['tilt']); cs.update(x[0] for x in m['topw'])
        cs.update(cu for cu, v in d['sec'].items() if v['rank'] <= LARGE_N)
    return cs


def build_ftd(cs):
    """FTD（決済の失敗の公表データ・半月ごと）から CUSIP ごと・月ごとの当時の記号・終値・名前 → ftd_index.json"""
    out = defaultdict(dict)   # cu → ym → [Counter(sym), last_px, desc]
    fd = os.path.join(C, 'ftd')
    for fn in sorted(os.listdir(fd)):
        if not fn.endswith('.zip'):
            continue
        z = zipfile.ZipFile(os.path.join(fd, fn))
        txt = z.read(z.namelist()[0]).decode('latin-1')
        for line in txt.splitlines()[1:]:
            parts = line.split('|')
            if len(parts) < 6:
                continue
            cu = norm_cusip(parts[1])
            if cu not in cs:
                continue
            try:
                ym = int(parts[0][:6]); pxv = float(parts[5]) if parts[5].strip() not in ('', '.') else None
            except ValueError:
                continue
            sym = parts[2].strip().upper()
            e = out[cu].setdefault(ym, [Counter(), None, parts[4].strip()])
            if sym:
                e[0][sym] += 1
            if pxv:
                e[1] = pxv
    js = {cu: {str(ym): [dict(v[0]), v[1], v[2]] for ym, v in d.items()} for cu, d in out.items()}
    json.dump(js, open(os.path.join(C, 'ftd_index.json'), 'w'))
    print('FTD: 候補', len(cs), '→ FTD に出た', len(js))
    return js


def load_ftd():
    return json.load(open(os.path.join(C, 'ftd_index.json')))


_ftd_memo = {}


def ftd_symbols(ftd, cu, p):
    """p（yyyymm）に近い月ほど先に、当時の記号の候補を並べる"""
    k = (id(ftd), cu, p)
    if k not in _ftd_memo:
        _ftd_memo[k] = _ftd_symbols(ftd, cu, p)
    return _ftd_memo[k]


def _ftd_symbols(ftd, cu, p):
    d = ftd.get(cu) or {}
    if not d:
        return [], None
    order = sorted(d, key=lambda ym: (abs((int(ym) // 100 - p // 100) * 12 + int(ym) % 100 - p % 100), -int(ym)))
    syms, desc = [], None
    for ym in order:
        c, _, ds = d[ym]
        desc = desc or ds
        for s_, _ in sorted(c.items(), key=lambda x: -x[1]):
            if s_ not in syms:
                syms.append(s_)
    return syms, desc


def figi_map(cs):
    """OpenFIGI（鍵なし: 1分25回・1回10件）で CUSIP → 記号・証券の種類。結果は figi.json に貯める"""
    path = os.path.join(C, 'figi.json')
    have = json.load(open(path)) if os.path.exists(path) else {}
    todo = [cu for cu in sorted(cs) if cu not in have]
    print('OpenFIGI: 未取得', len(todo), '件', flush=True)
    for i in range(0, len(todo), 10):
        batch = todo[i:i + 10]
        body = json.dumps([{'idType': 'ID_CUSIP', 'idValue': cu} for cu in batch]).encode()
        for k in range(6):
            try:
                req = urllib.request.Request('https://api.openfigi.com/v3/mapping', data=body,
                                             headers={'Content-Type': 'application/json'})
                res = json.loads(urllib.request.urlopen(req, timeout=60).read())
                break
            except urllib.error.HTTPError as e:
                time.sleep(15 if e.code == 429 else 5 * (k + 1)); res = None
            except Exception:  # noqa
                time.sleep(5 * (k + 1)); res = None
        if res is None:
            print('  OpenFIGI 失敗', batch[0]); continue
        for cu, r in zip(batch, res):
            data = r.get('data') or []
            us = [x for x in data if x.get('exchCode') == 'US'] or data
            if us:
                x = us[0]
                have[cu] = {k2: x.get(k2) for k2 in ('ticker', 'name', 'securityType', 'securityType2', 'marketSector', 'exchCode')}
            else:
                have[cu] = {'none': r.get('warning') or r.get('error') or 'no data'}
        if (i // 10) % 50 == 0:
            json.dump(have, open(path, 'w')); print('  OpenFIGI', i + len(batch), '/', len(todo), flush=True)
        time.sleep(2.45)
    json.dump(have, open(path, 'w'))
    return have


def load_figi():
    path = os.path.join(C, 'figi.json')
    return json.load(open(path)) if os.path.exists(path) else {}


def is_nonstock(cu, figi, ftd_desc, sec_row):
    f = figi.get(cu) or {}
    if f.get('securityType') in NONSTOCK_TYPES or f.get('securityType2') in ('Mutual Fund', 'ETP'):
        return 'figi_' + str(f.get('securityType'))
    if f.get('marketSector') and f.get('marketSector') != 'Equity':
        return 'figi_sector_' + str(f.get('marketSector'))
    if ftd_desc and FTD_FUND_RE.search(ftd_desc):
        return 'ftd_fund'
    return None


BANK_RE = re.compile(r'\bBANK\b|\bBANCORP|\bBANCSHARES|\bBANKSHARES|\bBANC\b|TRUST CO\b|TRUST COMPANY|NATIONAL ASSOCIATION|'
                     r'\bN\.?\s?A\.?$|\bSAVINGS\b|CREDIT UNION|INSURANCE|ASSURANCE|LIFE INS', re.I)
MIN_HOLDERS = 3                   # best idea の候補は 13F 提出者の3社以上が持つ株（上場していない持分・CUSIP の打ち間違いを除く）


def eligible(m):
    """銀行の信託部門・保険会社（顧客の古い持ち株・戦略的な持分が多い）を除く。受動的な名前・銘柄数・ETF 比率は --parse で除外済み"""
    return not BANK_RE.search(m['name'] or '')


def pick_best(P, figi, ftd, key='tilt'):
    """運用者ごとの best idea（傾き上位から、株でないと分かったもの・持ち手が3社未満のものを飛ばした最初の1つ）。
    分類できない（OpenFIGI も FTD も知らない）ものは株として残す（価格が取れなければ未観測として囲む）"""
    out = {}
    for p, d in P.items():
        bi = []
        for m in d['managers']:
            if not eligible(m):
                continue
            for x in m[key]:
                cu = x[0]
                if ((d['sec'].get(cu) or {}).get('holders') or 0) < MIN_HOLDERS:
                    continue
                _, desc = ftd_symbols(ftd, cu, p)
                if is_nonstock(cu, figi, desc, d['sec'].get(cu)):
                    continue
                bi.append((m['cik'], cu, x[1], x[2] if key == 'tilt' else None))
                break
        out[p] = bi
    return out


def do_map():
    P = all_periods_data()
    cs = candidate_cusips(P)
    ftd = build_ftd(cs) if not os.path.exists(os.path.join(C, 'ftd_index.json')) else load_ftd()
    figi = load_figi()
    # 反復: 暫定の best idea を OpenFIGI で分類 → 株でないものを飛ばして次の候補 → 新しく出た CUSIP も分類
    for it in range(4):
        need = set()
        for key in ('tilt', 'topw'):
            for p, bi in pick_best(P, figi, ftd, key).items():
                need.update(cu for _, cu, _, _ in bi)
        for d in P.values():
            need.update(cu for cu, v in d['sec'].items() if v['rank'] <= LARGE_N)
        need -= set(figi)
        print('反復', it, '新しく分類する CUSIP', len(need), flush=True)
        if not need:
            break
        figi = figi_map(need)


# ───────────────────────── Yahoo（月次・照合つき） ─────────────────────────
def yh_path(sym):
    return os.path.join(YHD, sym.replace('/', '_') + '.json')


def yh_fetch(sym):
    os.makedirs(YHD, exist_ok=True)
    pth = yh_path(sym)
    if os.path.exists(pth):
        return 'cached'
    alt = os.path.join(IE_YH, sym + '.json')        # index_events が取った同じ形式の月次（読むだけ）
    if os.path.exists(alt) and os.path.getsize(alt) > 0:
        return 'ie_yh'
    u = (f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}?period1=0&period2={int(time.time())}'
         f'&interval=1mo&events=div%2Csplit')
    for i in range(5):
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers=M.UA), timeout=60).read()
            tmp = pth + f'.{os.getpid()}.tmp'
            open(tmp, 'wb').write(b); os.replace(tmp, pth)
            return 'ok'
        except urllib.error.HTTPError as e:
            if e.code == 404:
                open(pth, 'w').write('{"http":404}'); return '404'
            time.sleep(4 * (i + 1) if e.code == 429 else 2 * (i + 1))
        except Exception:  # noqa
            time.sleep(2 * (i + 1))
    return 'fail'


_yh = {}


def yh_load(sym):
    """→ {'close': {ym: 分割調整済みの終値}, 'adj': {ym: 配当込み}, 'splits': [(ym, 比)], 'ret': {ym: r}} or None"""
    if sym in _yh:
        return _yh[sym]
    out = None
    for pth in (yh_path(sym), os.path.join(IE_YH, sym + '.json')):
        if not os.path.exists(pth):
            continue
        try:
            j = json.load(open(pth))
        except Exception:  # noqa
            continue
        res = (j.get('chart') or {}).get('result') if isinstance(j, dict) else None
        if not res:
            continue
        r = res[0]
        ts = r.get('timestamp') or []
        q = (r['indicators'].get('quote') or [{}])[0].get('close') or []
        ad = ((r['indicators'].get('adjclose') or [{}])[0].get('adjclose')) or q
        close, adj = {}, {}
        for t, c_, a_ in zip(ts, q, ad):
            d = datetime.datetime.utcfromtimestamp(t)
            k = d.year * 100 + d.month
            if k > END:
                continue
            if c_ is not None and c_ > 0:
                close[k] = c_
            if a_ is not None and a_ > 0:
                adj[k] = a_
        splits = []
        for ev in ((r.get('events') or {}).get('splits') or {}).values():
            d = datetime.datetime.utcfromtimestamp(ev['date'])
            if ev.get('numerator') and ev.get('denominator'):
                splits.append((d.year * 100 + d.month, ev['numerator'] / ev['denominator']))
        ret, ks = {}, sorted(adj)
        spike = None
        for a0, k in zip(ks, ks[1:]):
            if madd(a0, 1) != k:
                continue                      # 欠けた月をまたぐリターンは作らない
            x = adj[k] / adj[a0] - 1
            if x > SPIKE:
                spike = k; break              # データの誤り → この月から先は未観測
            ret[k] = x
        out = {'close': close, 'adj': adj, 'splits': splits, 'ret': ret, 'spike': spike,
               'type': r['meta'].get('instrumentType'), 'name': r['meta'].get('longName') or r['meta'].get('shortName')}
        break
    _yh[sym] = out
    return out


def raw_close(y, ym):
    """分割を戻した当時の終値（Yahoo の close は後の分割で調整済み）"""
    c = y['close'].get(ym)
    if c is None:
        return None
    f = 1.0
    for sm, ratio in y['splits']:
        if sm > ym:
            f *= ratio
    return c * f


def sym_variants(s_):
    s_ = s_.strip().upper().replace('/', '-').replace(' ', '-').replace('.', '-')
    out = [s_]
    if len(s_) >= 4 and '-' not in s_ and s_[-1] in 'ABCK':
        out.append(s_[:-1] + '-' + s_[-1])     # FTD は種類株の区切りを落とす（BRKB → BRK-B）
    return out


def candidates_for(cu, p, ftd, figi):
    syms, _ = ftd_symbols(ftd, cu, p)
    out = []
    for s_ in syms[:4]:
        for v in sym_variants(s_):
            if v not in out:
                out.append(v)
    t = (figi.get(cu) or {}).get('ticker')
    if t:
        for v in sym_variants(t):
            if v not in out:
                out.append(v)
    return out[:8]


def ref_price(cu, p, P, ipx=None):
    """照合に使う 13F の当時の株価（$）: 集計の合意（3社以上）→ なければその運用者の暗黙の株価"""
    v = (P[p]['sec'].get(cu) or {}).get('px_usd')
    return v if v else ipx


def resolve(tasks, P, ftd, figi, fetch=True, rounds=8, threads=4):
    """tasks = {(cu, p): ref_px} → {(cu, p): 記号 or None}。候補の記号を順に試し、当時の株価が PX_TOL 以内で合った最初の1つ"""
    import concurrent.futures as cf
    cands = {k: candidates_for(k[0], k[1], ftd, figi) for k in tasks}
    pos = {k: 0 for k in tasks}
    done = {}
    for rd in range(rounds):
        want = {k: cands[k][pos[k]] for k in tasks if k not in done and pos[k] < len(cands[k])}
        if not want:
            break
        syms = sorted(set(want.values()))
        if fetch:
            todo = [s_ for s_ in syms if not os.path.exists(yh_path(s_)) and not os.path.exists(os.path.join(IE_YH, s_ + '.json'))]
            print(f'  照合 {rd}: 対象 {len(want)} 組・記号 {len(syms)}・未取得 {len(todo)}', flush=True)
            with cf.ThreadPoolExecutor(threads) as ex:
                res = list(ex.map(yh_fetch, todo))
            print('   ', Counter(res), flush=True)
        for k, s_ in want.items():
            y = yh_load(s_)
            ref = tasks[k]
            rc = raw_close(y, k[1]) if y else None
            if rc and ref and abs(rc / ref - 1) <= PX_TOL:
                done[k] = s_
            else:
                pos[k] += 1
    return {k: done.get(k) for k in tasks}


def all_tasks(P, ftd, figi):
    """価格が要る (CUSIP, 期間) と照合の株価"""
    tasks = {}
    for key in ('tilt', 'topw'):
        for p, bi in pick_best(P, figi, ftd, key).items():
            for cik, cu, w, t in bi:
                if (cu, p) not in tasks:
                    tasks[(cu, p)] = None
    ipx = {}
    for p, d in P.items():
        for m in d['managers']:
            for x in m['tilt'] + m['topw']:
                if x[3]:
                    ipx.setdefault((x[0], p), []).append(x[3])
        for cu, v in d['sec'].items():
            if v['rank'] <= LARGE_N:
                tasks[(cu, p)] = None
    for k in tasks:
        tasks[k] = ref_price(k[0], k[1], P, S.median(ipx[k]) if k in ipx else None)
    return tasks


def do_fetch_yh():
    P = all_periods_data(); ftd = load_ftd(); figi = load_figi()
    tasks = all_tasks(P, ftd, figi)
    print('価格が要る (CUSIP, 期間)', len(tasks), '・CUSIP', len({k[0] for k in tasks}), flush=True)
    res = resolve(tasks, P, ftd, figi, fetch=True)
    json.dump({f'{k[0]}|{k[1]}': v for k, v in res.items()}, open(os.path.join(C, 'resolved.json'), 'w'))
    print('照合できた', sum(1 for v in res.values() if v), '/', len(res))


def load_resolved():
    j = json.load(open(os.path.join(C, 'resolved.json')))
    return {(k.split('|')[0], int(k.split('|')[1])): v for k, v in j.items()}


# ───────────────────────── 組み立て ─────────────────────────
PRIMARY = ['P1_A_ew_all', 'P2_B_vw_all', 'P3_C_consensus2_all', 'P4_D_top20_large']
EXPLOR = ['X1_A_ew_invest', 'X2_C_consensus2_invest', 'X3_E_topweight_ew', 'X4_F_concentrated_ew', 'X5_H_annual_ew_invest',
          'X6_D_top20_large_vw']
SANITY = ['S1_all_large500_vw', 'S2_all_large500_ew']
VERSIONS = {'O': None, 'P30': MISS_P30, 'P100': MISS_P100}
REAL = {'R1_GURU': 'GURU', 'R2_GVIP': 'GVIP', 'R3_ALFA': 'ALFA', 'R4_DDDIX': 'DDDIX'}
DESC = {
    'P1_A_ew_all': '全運用者の best idea（比重−集計の市場比重 が最大の株）を銘柄ごとに等しく',
    'P2_B_vw_all': '同じ集合を 13F の集計保有額（時価総額の代わり）で加重',
    'P3_C_consensus2_all': '2人以上の運用者が best idea に選んだ株を等しく',
    'P4_D_top20_large': '大型株（集計保有額の上位500）のうち best idea に選んだ運用者が多い上位20社を等しく（買える形）',
    'X1_A_ew_invest': 'P1 を集計保有額の上位1000（投資可能）に限る',
    'X2_C_consensus2_invest': 'P3 を上位1000に限る',
    'X3_E_topweight_ew': 'best idea を『比重が最大の株』（市場比重を引かない）にした版・等しく',
    'X4_F_concentrated_ew': 'P1 を株が10〜40銘柄の集中型の運用者だけに',
    'X5_H_annual_ew_invest': '年1回（12月末の報告・2月末に組む）・上位1000・12か月持つ（個人が回せる版）',
    'X6_D_top20_large_vw': 'P4 を集計保有額で加重',
    'S1_all_large500_vw': '検算: 大型株上位500を集計保有額で加重（≒S&P500。市場とほぼ同じになるはず）',
    'S2_all_large500_ew': '検算: 大型株上位500を等しく（≒RSP）',
}


def build_weights(P, figi, ftd):
    """戦略 → {期間 p: {CUSIP: 組む時の比重（合計1・未観測も含む）}}"""
    bt = pick_best(P, figi, ftd, 'tilt')
    bw = pick_best(P, figi, ftd, 'topw')
    W = {k: {} for k in PRIMARY + EXPLOR + SANITY}
    nmgr = {p: {m['cik']: m['n'] for m in d['managers']} for p, d in P.items()}
    for p, d in P.items():
        sec = d['sec']
        rk = lambda cu: (sec.get(cu) or {}).get('rank', 10 ** 9)
        av = lambda cu: (sec.get(cu) or {}).get('agg_usd', 0) or 0
        cnt = Counter(cu for _, cu, _, _ in bt[p])
        uniq = sorted(cnt)
        ew = lambda xs: {cu: 1 / len(xs) for cu in xs} if xs else {}

        def vw(xs):
            t = sum(av(cu) for cu in xs)
            return {cu: av(cu) / t for cu in xs} if t > 0 else {}
        W['P1_A_ew_all'][p] = ew(uniq)
        W['P2_B_vw_all'][p] = vw(uniq)
        W['P3_C_consensus2_all'][p] = ew([cu for cu in uniq if cnt[cu] >= 2])
        large = sorted([cu for cu in uniq if rk(cu) <= LARGE_N], key=lambda cu: (-cnt[cu], -av(cu)))[:TOPK]
        W['P4_D_top20_large'][p] = ew(large)
        W['X6_D_top20_large_vw'][p] = vw(large)
        W['X1_A_ew_invest'][p] = ew([cu for cu in uniq if rk(cu) <= INVEST_N])
        W['X2_C_consensus2_invest'][p] = ew([cu for cu in uniq if cnt[cu] >= 2 and rk(cu) <= INVEST_N])
        W['X3_E_topweight_ew'][p] = ew(sorted({cu for _, cu, _, _ in bw[p]}))
        W['X4_F_concentrated_ew'][p] = ew(sorted({cu for cik, cu, _, _ in bt[p] if nmgr[p][cik] <= 40}))
        if p % 100 == 12:
            W['X5_H_annual_ew_invest'][p] = ew([cu for cu in uniq if rk(cu) <= INVEST_N])
        l500 = [cu for cu, v in sec.items() if v['rank'] <= LARGE_N]
        W['S1_all_large500_vw'][p] = vw(l500)
        W['S2_all_large500_ew'][p] = ew(l500)
    return W, {p: len(bt[p]) for p in bt}, {p: Counter(cu for _, cu, _, _ in bt[p]) for p in bt}


def hold_months(strategy, p):
    f = formation(p)
    n = 12 if strategy.startswith('X5') else 3
    return [madd(f, i) for i in range(1, n + 1)]


def status(cu, p, res):
    """ok / unmapped（記号が照合できない＝未観測）/ gone_before（照合できたが組む月の前に取引が終わった＝誰も買えない）"""
    sym = res.get((cu, p))
    if not sym:
        return 'unmapped', None
    y = yh_load(sym)
    f = formation(p)
    if y is None:
        return 'unmapped', None
    if y['adj'].get(f) is None or (y['spike'] and y['spike'] <= f):
        later = [k for k in y['adj'] if f < k <= madd(f, 3)]
        return ('unmapped', None) if later else ('gone_before', None)
    return 'ok', y


def port_returns(W, strategy, res, L):
    """買って持つ（期間内は比重が漂う）月次リターン。L=None は観測できる社で按分（O）、数値なら未観測の最初の月に L・以後 0"""
    out, cov, turn = {}, [], []
    prev_end = None     # 前の保有の終わりの比重 {cu or '_cash': w}
    for p in sorted(W[strategy]):
        w0 = W[strategy][p]
        if not w0:
            continue
        ms = [m for m in hold_months(strategy, p) if m <= END]
        if not ms:
            continue
        st = {cu: status(cu, p, res) for cu in w0}
        live = {cu: w for cu, w in w0.items() if st[cu][0] != 'gone_before'}
        tot = sum(live.values())
        if tot <= 0:
            continue
        if L is None:
            v = {cu: w for cu, w in live.items() if st[cu][0] == 'ok'}
        else:
            v = dict(live)
        tv = sum(v.values())
        if tv <= 0:
            continue
        v = {cu: w / tv for cu, w in v.items()}
        cov.append({'p': p, 'n': len(w0), 'n_ok': sum(1 for x in st.values() if x[0] == 'ok'),
                    'n_unmapped': sum(1 for x in st.values() if x[0] == 'unmapped'),
                    'n_gone_before': sum(1 for x in st.values() if x[0] == 'gone_before'),
                    'w_unmapped': round(sum(w for cu, w in live.items() if st[cu][0] == 'unmapped') / tot, 4)})
        if prev_end is not None:
            keys = set(v) | set(prev_end)
            turn.append(0.5 * sum(abs(v.get(k, 0) - prev_end.get(k, 0)) for k in keys))
        alive = {cu: (st[cu][0] == 'ok') for cu in v}
        cash = 0.0
        for m in ms:
            V0 = sum(v.values()) + cash
            if L is None:
                obs = {cu: st[cu][1]['ret'][m] for cu in v if alive[cu] and m in st[cu][1]['ret']}
                for cu in v:
                    if alive[cu] and cu not in obs:
                        alive[cu] = False
                base = sum(v[cu] for cu in obs)
                if base <= 0:
                    break
                R = sum(v[cu] * r for cu, r in obs.items()) / base
                newv = {cu: v[cu] * (1 + obs[cu]) for cu in obs}
                scale = V0 * (1 + R) / sum(newv.values())
                v = {cu: x * scale for cu, x in newv.items()}
                alive = {cu: True for cu in v}
                out[m] = R
            else:
                newv = {}
                for cu, x in v.items():
                    if not alive[cu]:
                        continue
                    r = st[cu][1]['ret'].get(m) if st[cu][0] == 'ok' else None
                    if r is None:
                        cash += x * (1 + L); alive[cu] = False
                    else:
                        newv[cu] = x * (1 + r)
                v = newv; alive = {cu: True for cu in v}
                R = (sum(v.values()) + cash) / V0 - 1
                out[m] = R
        T = sum(v.values()) + cash
        prev_end = {cu: x / T for cu, x in v.items()} if T > 0 else {}
        if cash > 0 and T > 0:
            prev_end['_cash'] = cash / T
    per_year = 1 if strategy.startswith('X5') else 4
    ann_turn = (S.mean(turn) * per_year) if turn else None
    return out, cov, ann_turn


# ───────────────────────── 統計 ─────────────────────────
def ols_hac(y, X, lag=12):
    import numpy as np
    y = np.asarray(y); X = np.column_stack([np.ones(len(y))] + [np.asarray(c) for c in X])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    n = len(y)
    XtXi = np.linalg.inv(X.T @ X)
    Sm = (X * e[:, None]).T @ (X * e[:, None])
    for L_ in range(1, lag + 1):
        w = 1 - L_ / (lag + 1)
        G = (X[L_:] * e[L_:, None]).T @ (X[:-L_] * e[:-L_, None])
        Sm += w * (G + G.T)
    V = XtXi @ Sm @ XtXi
    return b, np.sqrt(np.diag(V))


def factor_alpha(s, rf, facs):
    ks = sorted(k for k in s if k in rf and all(k in f for f in facs.values()))
    if len(ks) < 36:
        return None
    y = [s[k] - rf[k] for k in ks]
    names = list(facs)
    b, se = ols_hac(y, [[facs[n][k] for k in ks] for n in names])
    return {'alpha_ann': round(b[0] * 1200, 2), 't': round(b[0] / se[0], 2), 'n': len(ks),
            'loadings': {n: round(float(b[i + 1]), 2) for i, n in enumerate(names)}}


def load_factors():
    ff = M.ff_factors()
    f5 = None
    for t, v in M.french_tables('F-F_Research_Data_5_Factors_2x3').items():
        if v['freq'] == 'monthly':
            f5 = {c.lower().replace('-', ''): {d: row[i] / 100 for d, row in v['data'].items() if row[i] is not None}
                  for i, c in enumerate(v['cols'])}
            break
    mom = None
    for t, v in M.french_tables('F-F_Momentum_Factor').items():
        if v['freq'] == 'monthly':
            mom = {d: row[0] / 100 for d, row in v['data'].items() if row[0] is not None}
            break
    return ff, {'mktrf': f5['mktrf'], 'smb': f5['smb'], 'hml': f5['hml'], 'rmw': f5['rmw'], 'cma': f5['cma'], 'umd': mom}


def evaluate(name, fam, desc, s, b, spy, rf, facs, turnover, cost, holm_p=None, real=False):
    full = M.excess_stats(s, b)
    hold = M.excess_stats(s, b, a=M.HOLD_START)
    recent = M.excess_stats(s, b, a=M.RECENT_START)
    train = M.excess_stats(s, b, z=M.TRAIN_END)
    sn = s if (real or turnover is None) else M.apply_cost(s, turnover, cost)
    cost_hold = M.excess_stats(sn, b, a=M.HOLD_START)
    roll20, roll10 = M.rolling(s, b, 20), M.rolling(s, b, 10)
    dca20, dca10 = M.dca(s, b, 20), M.dca(s, b, 10)
    g, crit = M.grade(full, train, hold, roll20, cost_hold, repl=None, family_holm_p=holm_p)
    return {'name': name, 'family': fam, 'description': desc, 'months': len(s),
            'from': min(s) if s else None, 'to': max(s) if s else None,
            'turnover_oneway_annual': round(turnover, 2) if turnover is not None else None,
            'cost_per_unit': cost if not real else None,
            'full': full, 'train': train, 'hold': hold, 'recent': recent, 'net_cost_hold': cost_hold,
            'roll20': roll20, 'roll10_ref': roll10, 'dca20': dca20, 'dca10_ref': dca10,
            'vs_spy': M.excess_stats(s, spy), 'max_dd': round(M.maxdd(s) * 100, 1) if s else None,
            'max_dd_mkt_same_window': round(M.maxdd({k: b[k] for k in s if k in b}) * 100, 1) if s else None,
            'ff5_umd_alpha': factor_alpha(s, rf, facs), 'holm_p_hold': holm_p, 'grade': g, 'criteria': crit}


# ───────────────────────── 道 Q: 13F の四半期末の株価で測る（生き残りの偏りが小さい） ─────────────────────────
SPLIT_C = sorted({x for b_ in (2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 50, 100, 1.5, 1.25, 1.2,
                               1.02, 1.03, 1.04, 1.05, 1.06, 1.08, 1.1) for x in (b_, 1 / b_)} | {1.0})
Q_SPIKE = 3.0                     # 四半期 +300% 超はデータの誤り → 未観測
_qpx = {}


def qpx(p):
    if p not in _qpx:
        pth = os.path.join(C, f'qpx_{p}.json')
        _qpx[p] = json.load(open(pth)) if os.path.exists(pth) else None
    return _qpx[p]


def split_factor(cu, q0, q1):
    """q0→q1 の株数の倍率（分割・株式配当）。両方に居る持ち手の株数の比の最頻値が分割の候補に一致し（±1%）、
    持ち手の2割以上（3社以上）がちょうどその比なら採る。株価の動きで裏を取る（直すと株価の比が1へ近づくときだけ）"""
    a, b_ = qpx(q0).get(cu), qpx(q1).get(cu)
    if not a or not b_:
        return 1.0, 'no_data'
    ha, hb = a[2], b_[2]
    com = [c for c in ha if c in hb and ha[c] > 0]
    if len(com) < 3:
        return 1.0, 'few_common'
    rs = Counter(round(hb[c] / ha[c], 3) for c in com)
    r, n = rs.most_common(1)[0]
    if n < max(3, 0.2 * len(com)):
        return 1.0, 'no_mode'
    cand = min(SPLIT_C, key=lambda x: abs(math.log(r / x)))
    if abs(r / cand - 1) > 0.01 or cand == 1.0:
        return 1.0, 'none'
    pr = b_[0] / a[0] if a[0] > 0 else None
    if pr and abs(math.log(pr * cand)) < abs(math.log(pr)):
        return cand, 'split'
    return 1.0, 'unconfirmed'


def q_ret(cu, q0, q1):
    """四半期末 q0→q1 の価格リターン（配当なし・分割調整） or None（q1 に居ない＝期中に消えた）"""
    a, b_ = qpx(q0).get(cu), qpx(q1).get(cu)
    if not a or not b_ or a[0] <= 0 or b_[0] <= 0:
        return None
    k, _ = split_factor(cu, q0, q1)
    r = b_[0] * k / a[0] - 1
    return None if r > Q_SPIKE else r


def port_returns_q(W, strategy, L):
    """道 Q: p の 13F で組み、四半期末 p+3 で買い、p+6 まで持つ（X5 は p+15 まで）。L=None は O"""
    out, cov = {}, []
    for p in sorted(W[strategy]):
        w0 = W[strategy][p]
        if not w0:
            continue
        nq = 4 if strategy.startswith('X5') else 1
        qs = [madd(p, 3 * (i + 1)) for i in range(nq + 1)]
        qs = [q for q in qs if q <= END and qpx(q) is not None]
        if len(qs) < 2:
            continue
        h0 = qs[0]
        live = {cu: w for cu, w in w0.items() if (qpx(h0) or {}).get(cu)}
        gone = len(w0) - len(live)
        t = sum(live.values())
        if t <= 0:
            continue
        v = {cu: w / t for cu, w in live.items()}
        cash, nmiss = 0.0, 0
        for q0, q1 in zip(qs, qs[1:]):
            V0 = sum(v.values()) + cash
            rs = {cu: q_ret(cu, q0, q1) for cu in v}
            miss = [cu for cu, r in rs.items() if r is None]
            nmiss += len(miss)
            if L is None:
                obs = {cu: r for cu, r in rs.items() if r is not None}
                base = sum(v[cu] for cu in obs)
                if base <= 0:
                    break
                R = sum(v[cu] * r for cu, r in obs.items()) / base
                newv = {cu: v[cu] * (1 + r) for cu, r in obs.items()}
                sc = V0 * (1 + R) / sum(newv.values())
                v = {cu: x * sc for cu, x in newv.items()}
            else:
                newv = {}
                for cu, r in rs.items():
                    if r is None:
                        cash += v[cu] * (1 + L)
                    else:
                        newv[cu] = v[cu] * (1 + r)
                v = newv
                R = (sum(v.values()) + cash) / V0 - 1
            out[q1] = R
        cov.append({'p': p, 'n': len(w0), 'gone_before_h0': gone, 'vanished_in_hold': nmiss})
    return out, cov


def french_mkt_exdiv():
    """French の規模別（Lo30/Med40/Hi30＝全社）の配当なし時価加重リターンを、社数×平均規模で重み付けして配当なしの市場を作る。
    同じ作り方で配当ありの市場を作り French Mkt と突き合わせ、重みの時点（当月か前月か）を機械的に選ぶ"""
    def tabs(name):
        t = M.french_tables(name)
        g = lambda key: next(v for k, v in t.items() if key in k and v['freq'] == 'monthly')
        return g('Average Value Weight Returns'), g('Number of Firms'), g('Average Firm Size')
    ff = M.ff_factors()
    best = None
    for lagw in (0, 1):
        r, n, sz = tabs('Portfolios_Formed_on_ME')
        idx = [r['cols'].index(c) for c in ('Lo 30', 'Med 40', 'Hi 30')]
        mk = {}
        for m in r['data']:
            mw = madd(m, -lagw)
            if mw not in n['data'] or mw not in sz['data']:
                continue
            ws = [n['data'][mw][i] * sz['data'][mw][i] for i in idx]
            rr = [r['data'][m][i] for i in idx]
            if None in ws or None in rr:
                continue
            mk[m] = sum(w * x for w, x in zip(ws, rr)) / sum(ws) / 100
        ks = [k for k in mk if k in ff['mkt'] and k >= 196307]
        err = math.sqrt(sum((mk[k] - ff['mkt'][k]) ** 2 for k in ks) / len(ks))
        if best is None or err < best[1]:
            best = (lagw, err)
    lagw = best[0]
    r, n, sz = tabs('Portfolios_Formed_on_ME_Wout_Div')
    idx = [r['cols'].index(c) for c in ('Lo 30', 'Med 40', 'Hi 30')]
    ex = {}
    for m in r['data']:
        mw = madd(m, -lagw)
        if mw not in n['data'] or mw not in sz['data']:
            continue
        ws = [n['data'][mw][i] * sz['data'][mw][i] for i in idx]
        rr = [r['data'][m][i] for i in idx]
        if None in ws or None in rr:
            continue
        ex[m] = sum(w * x for w, x in zip(ws, rr)) / sum(ws) / 100
    return ex, {'weight_lag_months': lagw, 'rmse_vs_french_mkt_monthly_pct': round(best[1] * 100, 4)}


def to_quarters(mret, qkeys):
    """月次 → 四半期末 q の3か月（q-2..q）の複利"""
    out = {}
    for q in qkeys:
        ms = [madd(q, -2), madd(q, -1), q]
        if all(m in mret for m in ms):
            out[q] = (1 + mret[ms[0]]) * (1 + mret[ms[1]]) * (1 + mret[ms[2]]) - 1
    return out


def evaluate_q(name, fam, desc, s, b, turnover, cost, holm_p=None):
    full = M.excess_stats(s, b, per_year=4, lag=4)
    hold = M.excess_stats(s, b, a=M.HOLD_START, per_year=4, lag=4)
    recent = M.excess_stats(s, b, a=M.RECENT_START, per_year=4, lag=4)
    train = M.excess_stats(s, b, z=M.TRAIN_END, per_year=4, lag=4)
    sn = M.apply_cost(s, turnover, cost, per_year=4) if turnover is not None else s
    cost_hold = M.excess_stats(sn, b, a=M.HOLD_START, per_year=4, lag=4)
    g, crit = M.grade(full, train, hold, None, cost_hold, repl=None, family_holm_p=holm_p)
    return {'name': name, 'family': fam, 'description': desc, 'quarters': len(s), 'from': min(s) if s else None,
            'to': max(s) if s else None, 'turnover_oneway_annual': round(turnover, 2) if turnover is not None else None,
            'cost_per_unit': cost, 'full': full, 'train': train, 'hold': hold, 'recent': recent, 'net_cost_hold': cost_hold,
            'roll20': None, 'max_dd_quarterly': round(M.maxdd(s) * 100, 1) if s else None,
            'holm_p_hold': holm_p, 'grade': g, 'criteria': crit}


def git_sha(path):
    try:
        return subprocess.check_output(['git', 'log', '-1', '--format=%H', '--', path], cwd=BASE, text=True).strip() or None
    except Exception:  # noqa
        return None


def coverage():
    """被覆だけ数える（戦略と市場の比較は計算しない）"""
    P = all_periods_data(); ftd = load_ftd(); figi = load_figi()
    res = load_resolved() if os.path.exists(os.path.join(C, 'resolved.json')) else {}
    W, nbi, cnt = build_weights(P, figi, ftd)
    rep = {}
    for k in PRIMARY + EXPLOR + SANITY:
        tot = Counter(); wun = []
        for p, w0 in W[k].items():
            for cu in w0:
                tot[status(cu, p, res)[0] if res else 'no_resolve'] += 1
            if res:
                live = {cu: w for cu, w in w0.items() if status(cu, p, res)[0] != 'gone_before'}
                t = sum(live.values())
                if t > 0:
                    wun.append(sum(w for cu, w in live.items() if status(cu, p, res)[0] == 'unmapped') / t)
        rep[k] = {'positions': dict(tot), 'mean_names': round(sum(len(w) for w in W[k].values()) / max(1, len(W[k])), 1),
                  'mean_w_unmapped': round(S.mean(wun), 4) if wun else None}
        print(k, rep[k])
    return rep


def main():
    P = all_periods_data(); ftd = load_ftd(); figi = load_figi(); res = load_resolved()
    ff, facs = load_factors()
    b, rf = ff['mkt'], ff['rf']
    spy = M.yahoo('SPY')
    W, nbi, cnt = build_weights(P, figi, ftd)
    series, covs, turns = {}, {}, {}
    for k in PRIMARY + EXPLOR + SANITY:
        for ver, L in VERSIONS.items():
            if k in SANITY and ver != 'O':
                continue
            r, cv, tn = port_returns(W, k, res, L)
            series[(k, ver)] = r; covs[(k, ver)] = cv; turns[(k, ver)] = tn
    cost_of = lambda k: COST_LARGE if (k.startswith('P4') or k.startswith('X6') or k.startswith('S')) else COST_SMALL
    tested = []
    holm = {}
    for ver in VERSIONS:
        pv = {}
        for k in PRIMARY:
            h = M.excess_stats(series[(k, ver)], b, a=M.HOLD_START)
            pv[k] = h['p'] if h else None
        holm[ver] = M.holm(pv)
    for k in PRIMARY + EXPLOR:
        for ver in VERSIONS:
            fam = 'primary' if k in PRIMARY else 'exploratory（事前登録済み・Holm の族の外）'
            e = evaluate(f'{k}__{ver}', fam, DESC[k] + f'（未観測の扱い {ver}）', series[(k, ver)], b, spy, rf, facs,
                         turns[(k, 'O')], cost_of(k), holm[ver].get(k) if k in PRIMARY else None)
            e['survivorship_version'] = ver
            cv = covs[(k, ver)]
            e['coverage'] = {'quarters': len(cv), 'mean_names': round(S.mean(c['n'] for c in cv), 1) if cv else None,
                             'mean_w_unmapped': round(S.mean(c['w_unmapped'] for c in cv), 4) if cv else None,
                             'gone_before_total': sum(c['n_gone_before'] for c in cv)}
            tested.append(e)
    for k in SANITY:
        e = evaluate(k, 'sanity（検算・戦略ではない）', DESC[k], series[(k, 'O')], b, spy, rf, facs, turns[(k, 'O')], cost_of(k))
        cv = covs[(k, 'O')]
        e['coverage'] = {'quarters': len(cv), 'mean_names': round(S.mean(c['n'] for c in cv), 1) if cv else None,
                         'mean_w_unmapped': round(S.mean(c['w_unmapped'] for c in cv), 4) if cv else None}
        tested.append(e)
    # 実在の器
    real = {}
    for k, t in REAL.items():
        try:
            real[k] = M.yahoo(t)
        except Exception as ex:  # noqa
            real[k] = None
            tested.append({'name': k, 'family': 'real（実在の器）', 'description': f'{t}: Yahoo に無い（{ex}）', 'grade': 'C',
                           'criteria': None, 'unavailable': True})
    rp = {}
    for k, r in real.items():
        if r:
            h = M.excess_stats(r, b, a=M.HOLD_START)
            rp[k] = h['p'] if h else None
    rholm = M.holm(rp)
    for k, r in real.items():
        if r:
            e = evaluate(k, 'real（実在の器・信託報酬控除後）', f'{REAL[k]}（Yahoo 配当込み・生き残りの偏りあり）', r, b, spy, rf, facs,
                         None, None, rholm.get(k), real=True)
            tested.append(e)
    # 検算
    sanity = {'french_mkt_cagr_2007_': round(M.cagr(M.window(b, M.HOLD_START)) * 100, 2),
              'french_mkt_cagr_1926_': round(M.cagr(b) * 100, 2),
              'spy_vs_french_mkt_same_window': M.excess_stats(spy, b, a=201309),
              'rsp_vs_S2_all_large500_ew': None}
    try:
        rsp = M.yahoo('RSP')
        sanity['rsp_vs_S2_all_large500_ew'] = M.excess_stats(series[('S2_all_large500_ew', 'O')], rsp)
        sanity['spy_vs_S1_all_large500_vw'] = M.excess_stats(series[('S1_all_large500_vw', 'O')], spy)
    except Exception as ex:  # noqa
        sanity['rsp_error'] = str(ex)
    # ── 道 Q: 13F の四半期末の株価（配当なし）vs French の配当なしの市場 ──
    exdiv, exdiv_info = french_mkt_exdiv()
    qkeys = sorted({madd(p, 3 * i) for p in P for i in range(1, 6)})
    bq = to_quarters(exdiv, qkeys)
    bq_div = to_quarters(b, qkeys)
    seriesQ, covQ = {}, {}
    for k in PRIMARY + EXPLOR + SANITY:
        for ver, L in VERSIONS.items():
            if k in SANITY and ver != 'O':
                continue
            r, cv = port_returns_q(W, k, L)
            seriesQ[(k, ver)] = r; covQ[(k, ver)] = cv
    holmQ = {}
    for ver in VERSIONS:
        pv = {}
        for k in PRIMARY:
            h = M.excess_stats(seriesQ[(k, ver)], bq, a=M.HOLD_START, per_year=4, lag=4)
            pv[k] = h['p'] if h else None
        holmQ[ver] = M.holm(pv)
    for k in PRIMARY + EXPLOR + SANITY:
        for ver in VERSIONS:
            if k in SANITY and ver != 'O':
                continue
            fam = ('Q_primary（道 Q・頑健性の族）' if k in PRIMARY else
                   'Q_sanity（検算）' if k in SANITY else 'Q_exploratory（道 Q・事前登録済み・Holm の族の外）')
            e = evaluate_q(f'Q_{k}__{ver}', fam, DESC[k] + f'（道 Q: 13F の四半期末の株価・配当なし／未観測の扱い {ver}）',
                           seriesQ[(k, ver)], bq, turns[(k, 'O')], cost_of(k), holmQ[ver].get(k) if k in PRIMARY else None)
            e['survivorship_version'] = ver
            cv = covQ[(k, ver)]
            e['coverage'] = {'quarters': len(cv), 'mean_names': round(S.mean(c['n'] for c in cv), 1) if cv else None,
                             'gone_before_h0_total': sum(c['gone_before_h0'] for c in cv),
                             'vanished_in_hold_total': sum(c['vanished_in_hold'] for c in cv)}
            tested.append(e)
    sanity['Q_exdiv_market'] = exdiv_info
    sanity['Q_french_div_minus_exdiv_ann_pct'] = M.excess_stats(bq_div, bq, a=201309, per_year=4, lag=4)
    per = [{'period': p, 'formation': formation(p), 'filings': d['n_filings'], 'eligible_managers': d['n_eligible'],
            'excluded': d['excluded'], 'best_ideas': nbi[p], 'unique_best_ideas': len(cnt[p]),
            'consensus2': sum(1 for v in cnt[p].values() if v >= 2), 'fix': d['fix']} for p, d in sorted(P.items())]
    top_bi = {str(p): [[(P[p]['sec'].get(cu) or {}).get('name'), cu, n] for cu, n in cnt[p].most_common(10)] for p in sorted(P)}
    res_stats = Counter('ok' if v else 'none' for v in res.values())
    out = {'angle': 'best_ideas_13f', 'prereg': 'out/' + PREREG, 'prereg_commit': git_sha(os.path.join('out', PREREG)),
           'tool': 'night/mw_best_ideas_13f.py', 'benchmark': 'French Mkt（Mkt-RF+RF・総リターン）', 'end': END,
           'n_tested': len(tested), 'holm_primary': holm, 'holm_primary_Q': holmQ, 'holm_real': rholm,
           'sanity': sanity, 'periods': per, 'top_best_ideas_by_period': top_bi,
           'price_resolution': {'pairs': len(res), **res_stats},
           'series_monthly': {f'{k}__{v}': {str(m): round(x, 6) for m, x in sorted(r.items())} for (k, v), r in series.items() if v == 'O' or k in PRIMARY},
           'series_quarterly_Q': {f'Q_{k}__{v}': {str(m): round(x, 6) for m, x in sorted(r.items())} for (k, v), r in seriesQ.items() if v == 'O' or k in PRIMARY},
           'benchmark_Q_exdiv_quarterly': {str(m): round(x, 6) for m, x in sorted(bq.items())},
           'tested': tested}
    M.save(OUT, out)
    for e in tested:
        if e.get('unavailable'):
            print(e['name'], 'N/A'); continue
        h = e['hold']; nc = e['net_cost_hold']
        print(f"{e['name']:<38} {e['grade']} hold {h['ex_ann'] if h else None:>6} t {h['t'] if h else None:>5} "
              f"cagrΔ {h['cagr_diff'] if h else None:>6} net {nc['ex_ann'] if nc else None:>6} TO {e.get('turnover_oneway_annual')}")
    print('sanity', json.dumps(sanity, ensure_ascii=False)[:800])

if __name__ == '__main__':
    a = sys.argv[1:]
    if '--fetch' in a:
        fetch()
    if '--parse' in a:
        parse()
    if '--parse-q' in a:
        parse_q()
    if '--map' in a:
        do_map()
    if '--fetch-yh' in a:
        do_fetch_yh()
    if '--coverage' in a:
        coverage()
    if not a:
        main()
