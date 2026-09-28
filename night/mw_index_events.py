#!/usr/bin/env python3
"""night/mw_index_events.py — 角度 index_events（読むだけ・門の判定には不使用）

問い: 指数の出来事で決まる売買の少ない持ち方——元の S&P500 を凍結して持つ（Siegel & Schwartz 2006）・
      M&A 以外で外された社・直近に入った社を除いた市場・スピンオフ——と、その実在のファンド版
      （LEXCX・CSD・FPX）は、純粋な時価加重の米国株（French Mkt）に勝つか。

事前登録: out/mw_index_events_prereg.json（測る前にコミット）。線は out/mw_prereg.json（C1〜C8）を
mw_common.grade でそのまま当てる。株の再構成は Yahoo（上場廃止の履歴が消える）なので、
未観測の社を『持たない』(S) と『−100%』(L) の二本で囲み、符号が一致したときだけ格を付ける。

段
  --fetch-sec : スピンオフ（Form 10-12B）の一覧と各社の提出履歴を SEC から採る → out/_mw_cache/ie_sec/
  --fetch-yh  : 名簿の全記号・スピンオフの記号・ファンドの Yahoo 月次を採る → out/_mw_cache/ie_yh/
  (既定)      : 計算して out/mw_index_events.json を書く
"""
import csv, datetime, gzip, json, math, os, re, sys, time, urllib.request, urllib.error
import statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

CACHE = M.CACHE
YH = os.path.join(CACHE, 'ie_yh')
SEC = os.path.join(CACHE, 'ie_sec')
MEMB = os.path.join(CACHE, 'ie_sp500_components.csv')
MEMB_URL = 'https://raw.githubusercontent.com/fja05680/sp500/master/S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv'
WIKI_URL = ('https://en.wikipedia.org/w/api.php?action=query&prop=revisions&titles=List_of_S%26P_500_companies&rvlimit=1'
            '&rvstart=2026-06-01T00:00:00Z&rvdir=older&rvprop=ids%7Ctimestamp%7Ccontent&rvslots=main&format=json')
PRE = 'mw_index_events_prereg.json'
END = 202608                       # French の終わり
W_UNIT = 0.0008                    # E3: 1社 = 米国市場の 0.08%（事前登録の定数）
SPIKE = 3.0                        # 月 +300% 超はデータの誤り
MA_PAT = re.compile(r'acqui|merg|purchas|bought|buy-?out|take[ns]? private|went private|going private|privatiz|combin|takeover|tender|spun|spin|split|separat', re.I)
FUNDS_R = {'R1_LEXCX': 'LEXCX', 'R2_CSD': 'CSD', 'R3_FPX': 'FPX'}
FUNDS_X = {'X1_LSHAX': 'LSHAX', 'X2_IPO': 'IPO', 'X3_MERFX': 'MERFX', 'X4_PKW': 'PKW'}
TURN = {'E1a_frozen1996': (0.05, 0.001), 'E1b_frozen2007': (0.05, 0.001), 'E2a_deletions12': (2.0, 0.003),
        'E2b_deletions36': (1.0, 0.003), 'E3_mkt_minus_adds': (0.05, 0.001), 'E4_spinoffs24': (1.5, 0.003)}


# ───────────────────────── 月の算術 ─────────────────────────
def madd(m, k):
    y, mo = divmod(m, 100)
    t = y * 12 + (mo - 1) + k
    return (t // 12) * 100 + t % 12 + 1


def ym(d):  # 'YYYY-MM-DD' → yyyymm
    return int(d[:4]) * 100 + int(d[5:7])


def months(a, z):
    out, m = [], a
    while m <= z:
        out.append(m); m = madd(m, 1)
    return out


# ───────────────────────── 取得 ─────────────────────────
def sec_get(url, name, sleep=0.12):
    from retro_delisted import SEC_UA
    os.makedirs(SEC, exist_ok=True)
    p = os.path.join(SEC, name)
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return open(p, 'rb').read()
    err = None
    for i in range(4):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=SEC_UA), timeout=120).read()
            try:
                b = gzip.decompress(b)
            except OSError:
                pass
            open(p, 'wb').write(b)
            time.sleep(sleep)
            return b
        except urllib.error.HTTPError as e:
            if e.code == 404:
                open(p, 'wb').write(b'{"http":404}')
                return b'{"http":404}'
            err = e; time.sleep(3 * (i + 1))
        except Exception as e:  # noqa
            err = e; time.sleep(3 * (i + 1))
    raise RuntimeError(f'SEC 取得失敗 {url}: {err}')


def yh_fetch(t):
    """Yahoo 月次の生 JSON を ie_yh/{t}.json に置く（404 は {"http":404}）"""
    os.makedirs(YH, exist_ok=True)
    p = os.path.join(YH, f'{t}.json')
    if os.path.exists(p):
        return 'cached'
    y = t.replace('.', '-')
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{y}?period1=0&period2={int(time.time())}&interval=1mo&events=div%2Csplit'
    for i in range(3):
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers=M.UA), timeout=60).read()
            open(p, 'wb').write(b); return 'ok'
        except urllib.error.HTTPError as e:
            if e.code == 404:
                open(p, 'w').write('{"http":404}'); return '404'
            time.sleep(3 * (i + 1))
        except Exception:  # noqa
            time.sleep(3 * (i + 1))
    return 'fail'


def fetch_sec():
    """スピンオフの候補: efts（2001〜）＋ form.gz（1994〜2000）→ 各 CIK の submissions"""
    filers = {}   # cik -> {'first': date, 'names': set, 'forms': []}

    def add(cik, name, date, form):
        cik = int(cik)
        f = filers.setdefault(cik, {'first': date, 'names': set(), 'forms': []})
        f['first'] = min(f['first'], date); f['names'].add(name.strip()); f['forms'].append((date, form))
    for y in range(1994, 2001):
        for q in range(1, 5):
            b = sec_get(f'https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/form.gz', f'form_{y}Q{q}.idx')
            for line in b.decode('latin-1').splitlines():
                if not line.startswith('10-12B'):
                    continue
                parts = re.split(r'\s{2,}', line.strip())
                if len(parts) < 5:
                    continue
                form, name, cik, date = parts[0], parts[1], parts[2], parts[3]
                if form not in ('10-12B', '10-12B/A'):
                    continue
                if re.fullmatch(r'\d{8}', date):
                    date = f'{date[:4]}-{date[4:6]}-{date[6:]}'
                add(cik, name, date, form)
    for y in range(2001, 2027):
        frm = 0
        while True:
            u = f'https://efts.sec.gov/LATEST/search-index?forms=10-12B&dateRange=custom&startdt={y}-01-01&enddt={y}-12-31&from={frm}'
            j = json.loads(sec_get(u, f'efts_{y}_{frm}.json'))
            hits = j['hits']['hits']
            for h in hits:
                s = h['_source']
                if not any(f in ('10-12B', '10-12B/A') for f in [s.get('form')]):
                    continue
                for c, nm in zip(s['ciks'], s['display_names']):
                    add(c, re.sub(r'\s*\(CIK \d+\)$', '', nm), s['file_date'], s['form'])
            frm += len(hits)
            if not hits or frm >= j['hits']['total']['value']:
                break
    print('10-12B の提出会社', len(filers))
    subs = {}
    for i, cik in enumerate(sorted(filers)):
        b = sec_get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json', f'sub_{cik}.json')
        j = json.loads(b)
        if j.get('http') == 404:
            subs[cik] = None; continue
        rec = j['filings']['recent']
        forms = list(zip(rec['form'], rec['filingDate']))
        for f in j['filings'].get('files', []):
            jj = json.loads(sec_get(f"https://data.sec.gov/submissions/{f['name']}", f"sub_{f['name']}"))
            forms += list(zip(jj.get('form', []), jj.get('filingDate', [])))
        d0 = filers[cik]['first']
        per = sorted(d for fm, d in forms if fm in ('10-Q', '10-K', '10-K405', '10-KT', '10-Q/A', '10-K/A') and d > d0)
        subs[cik] = {'name': j.get('name'), 'tickers': j.get('tickers') or [], 'exchanges': j.get('exchanges') or [],
                     'sic': j.get('sic'), 'first_periodic': per[0] if per else None}
        if i % 200 == 0:
            print(' submissions', i, '/', len(filers))
    out = {str(c): {'first_10_12b': filers[c]['first'], 'names': sorted(filers[c]['names']), 'n_forms': len(filers[c]['forms']),
                    **(subs[c] or {'missing_submissions': True})} for c in filers}
    json.dump(out, open(os.path.join(CACHE, 'ie_spinoff_filers.json'), 'w'), ensure_ascii=False)
    print('書いた ie_spinoff_filers.json')


def fetch_yh():
    rows = load_membership()
    allt = sorted(set().union(*[s for _, s in rows]))
    sp = os.path.join(CACHE, 'ie_spinoff_filers.json')
    spin_t = []
    if os.path.exists(sp):
        for c, v in json.load(open(sp)).items():
            if v.get('tickers'):
                spin_t.append(v['tickers'][0])
    from collections import Counter
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(4) as ex:
        res = list(ex.map(yh_fetch, allt + sorted(set(spin_t)) + list(FUNDS_R.values()) + list(FUNDS_X.values()) + ['SPY', 'RSP']))
    print(Counter(res))


# ───────────────────────── 読む ─────────────────────────
def load_membership():
    if not os.path.exists(MEMB):
        open(MEMB, 'wb').write(M.get(MEMB_URL, name='ie_sp500_components.csv'))
    rows = [(r['date'], set(r['tickers'].split(','))) for r in csv.DictReader(open(MEMB))]
    rows.sort()
    return rows


def load_wiki():
    j = json.loads(M.get(WIKI_URL, name='ie_wiki_rev_2026-06-01.json', max_age_days=3650))
    rev = list(j['query']['pages'].values())[0]['revisions'][0]
    c = rev['slots']['main']['*']
    seg = c[c.find('id="changes"'):]
    seg = seg[:seg.find('\n|}')]

    def clean(s):
        s = re.sub(r'<ref[^>]*/>', '', s); s = re.sub(r'<ref[^>]*>.*?</ref>', '', s, flags=re.S)
        s = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]*)\]\]', r'\1', s); s = re.sub(r'\{\{[^}]*\}\}', '', s)
        return s.strip()
    out = []
    for blk in seg.split('\n|-')[1:]:
        b = blk.strip()
        if b.startswith('!'):
            continue
        cells = [clean(x) for x in re.split(r'\n\||\|\|', b.lstrip('|'))]
        if len(cells) < 6:
            continue
        try:
            d = datetime.datetime.strptime(cells[0].strip(), '%B %d, %Y').date()
        except ValueError:
            continue
        out.append({'date': d, 'add': cells[1].strip(), 'add_name': cells[2], 'rem': cells[3].strip(), 'rem_name': cells[4],
                    'reason': ' '.join(cells[5:])})
    return out, rev['revid']


_yh = {}


def yh(t):
    """{'type','first','ret':{yyyymm:r},'spike':bool} or None"""
    if t in _yh:
        return _yh[t]
    p = os.path.join(YH, f'{t}.json')
    out = None
    if os.path.exists(p):
        j = json.load(open(p))
        res = (j.get('chart') or {}).get('result') if isinstance(j, dict) else None
        if res:
            r = res[0]; ts = r.get('timestamp') or []
            adj = ((r['indicators'].get('adjclose') or [{}])[0].get('adjclose')) or r['indicators']['quote'][0]['close']
            px = {}
            for a, v in zip(ts, adj):
                if v is None or v <= 0:
                    continue
                d = datetime.datetime.utcfromtimestamp(a)
                px[d.year * 100 + d.month] = v
            ks = sorted(px)
            if ks:
                ret, spike = {}, None
                for p0, k in zip(ks, ks[1:]):
                    if k > END:
                        break
                    if madd(p0, 1) != k:     # 欠けた月をまたぐリターンは作らない
                        continue
                    x = px[k] / px[p0] - 1
                    if x > SPIKE:
                        spike = k; break     # データの誤り → この月から先を捨てる
                    ret[k] = x
                out = {'type': r['meta'].get('instrumentType'), 'first': ks[0], 'ret': ret, 'spike': spike,
                       'name': r['meta'].get('longName') or r['meta'].get('shortName')}
    _yh[t] = out
    return out


def obs(t, m, spell_start_m):
    """('ok', r) / ('missing', None) / ('spike', None)。spike = 月 +300% 超で打ち切った後（両方の上下限で最後の値で売却扱い）"""
    d = yh(t)
    if not d or d['type'] != 'EQUITY' or d['first'] > spell_start_m:
        return 'missing', None
    if d['spike'] and m >= d['spike']:
        return 'spike', None
    r = d['ret'].get(m)
    return ('ok', r) if r is not None else ('missing', None)


def obs_ret(t, m, spell_start_m):
    """ある社のある月のリターン（観測できなければ None）"""
    return obs(t, m, spell_start_m)[1]


def spells(rows):
    """記号ごとの名簿の一続きの期間 [(start_date, end_date)]"""
    sp, prev = {}, set()
    last_date = None
    for d, s in rows:
        for t in s - prev:
            sp.setdefault(t, []).append([d, None])
        for t in prev - s:
            sp[t][-1][1] = last_date
        prev, last_date = s, d
    for t in prev:
        sp[t][-1][1] = last_date
    return sp


def spell_of(sp, t, d):
    for a, b in sp.get(t, []):
        if a <= d <= b:
            return a, b
    return None


# ───────────────────────── 出来事 ─────────────────────────
def build_events(rows, wiki, sp):
    rem, add = [], []
    for (d0, s0), (d1, s1) in zip(rows, rows[1:]):
        D1 = datetime.date.fromisoformat(d1)
        for t in sorted(s0 - s1):
            w = [x for x in wiki if x['rem'] == t and abs((x['date'] - D1).days) <= 10]
            st = spell_of(sp, t, d0)
            e = {'t': t, 'date': d1, 'm': ym(d1), 'spell_start': ym(st[0]), 'wiki': bool(w)}
            if w:
                e['reason'] = w[0]['reason'][:200]
                e['cls'] = 'ma' if MA_PAT.search(w[0]['reason']) else 'nonma'
            elif d1 >= '2011-01-01':
                e['cls'] = 'rename'
            else:
                obs3 = all(obs_ret(t, madd(e['m'], k), e['spell_start']) is not None for k in (1, 2, 3))
                e['cls'] = 'nonma' if obs3 else 'unknown'
            rem.append(e)
        for t in sorted(s1 - s0):
            w = [x for x in wiki if x['add'] == t and abs((x['date'] - D1).days) <= 10]
            st = spell_of(sp, t, d1)
            e = {'t': t, 'date': d1, 'm': ym(d1), 'spell_start': ym(st[0]), 'wiki': bool(w)}
            e['cls'] = 'confirmed' if w else ('rename' if d1 >= '2011-01-01' else 'unconfirmed')
            add.append(e)
    return rem, add


def load_spinoffs():
    p = os.path.join(CACHE, 'ie_spinoff_filers.json')
    if not os.path.exists(p):
        return None, {}
    raw = json.load(open(p))
    ev, cnt = [], {'filers': len(raw), 'no_submissions': 0, 'not_completed': 0, 'sic6770': 0, 'completed': 0,
                   'observed': 0, 'no_ticker': 0, 'yahoo_missing': 0, 'yahoo_window_fail': 0, 'after_end': 0}
    for c, v in raw.items():
        if v.get('missing_submissions'):
            cnt['no_submissions'] += 1; continue
        if str(v.get('sic')) == '6770':
            cnt['sic6770'] += 1; continue
        if not v.get('first_periodic'):
            cnt['not_completed'] += 1; continue
        cnt['completed'] += 1
        f10 = ym(v['first_10_12b']); fp = ym(v['first_periodic'])
        e = {'cik': c, 'name': v.get('name'), 'first_10_12b': v['first_10_12b'], 'first_periodic': v['first_periodic'], 'obs': False}
        t = (v.get('tickers') or [None])[0]
        e['t'] = t
        if not t:
            cnt['no_ticker'] += 1
        else:
            d = yh(t)
            if not d or d['type'] != 'EQUITY':
                cnt['yahoo_missing'] += 1
            elif not (madd(f10, -1) <= d['first'] <= madd(fp, 6)):
                cnt['yahoo_window_fail'] += 1
            else:
                e['obs'] = True; e['entry'] = d['first']; cnt['observed'] += 1
        if not e['obs']:
            e['entry'] = fp          # 未観測: 最初の定期報告の月を分離の月の近似にする（L の −100% の置き場所だけに使う）
        if e['entry'] >= END:
            cnt['after_end'] += 1; continue
        ev.append(e)
    return ev, cnt


# ───────────────────────── ポートフォリオ ─────────────────────────
def frozen(names, snap_date, start, sp, bound):
    """凍結（買って持つ・等加重で開始）。bound: 'S' 観測できる社だけ／'L' 未観測は −100%"""
    pos, ss, unobs = {}, {}, []
    for t in sorted(names):
        st = spell_of(sp, t, snap_date)
        ss[t] = ym(st[0])
        if obs_ret(t, start, ss[t]) is not None:
            pos[t] = 1.0
        else:
            unobs.append(t)
    n_all = len(names)
    lost0 = len(unobs) if bound == 'L' else 0
    out, dropped, spikes = {}, [], 0
    for m in months(start, END):
        v0 = sum(pos.values()) + (lost0 if m == start else 0)
        cash, vo, v1 = 0.0, 0.0, 0.0
        for t in list(pos):
            st, r = obs(t, m, ss[t])
            if st == 'ok':
                vo += pos[t]; pos[t] *= 1 + r; v1 += pos[t]
            else:
                dropped.append((t, m)); spikes += st == 'spike'
                if bound == 'S' or st == 'spike':
                    cash += pos[t]      # 最後の値で売り、残りへ時価の比で再投資
                del pos[t]              # L の 'missing' はここで −100%
        if vo <= 0:
            break
        k = 1 + cash / vo
        out[m] = v1 * k / v0 - 1
        for t in pos:
            pos[t] *= k
        if not pos:
            break
    return out, {'n_names': n_all, 'observed_at_start': n_all - len(unobs), 'unobserved_at_start': len(unobs),
                 'dropped_later': len(dropped), 'spike_truncations': spikes, 'unobserved_list': unobs[:60]}


def updated_ew(rows, sp, a, z):
    """参考: 入れ替え続ける等加重 S&P500（同じ Yahoo・観測できる社だけ）"""
    out = {}
    snaps = [(ym(d), d, s) for d, s in rows]
    for m in months(a, z):
        prev = [x for x in snaps if x[0] < m]
        if not prev:
            continue
        _, d, s = prev[-1]
        rs = []
        for t in s:
            st = spell_of(sp, t, d)
            r = obs_ret(t, m, ym(st[0]))
            if r is not None:
                rs.append(r)
        if rs:
            out[m] = sum(rs) / len(rs)
    return out


def calendar_ew(events, H, bound, mkt, a, z, st_fn):
    """暦月の等加重: 出来事の月の末に買い H か月持つ。st_fn(e, m) → ('ok', r)/('missing', None)/('spike', None)。
    S: 観測できない月が来たらその社を外す（最後の値で売る＝等加重の按分）。L: 'missing' はその月 −100% にして外す。
    'spike' は両方で最後の値で売る"""
    out, lost, stats = {}, set(), {'months_empty': 0, 'pos_months': 0, 'pos_months_obs': 0, 'lost_L': 0, 'spike': 0}
    for m in months(a, z):
        act = [e for e in events if e['entry'] < m <= madd(e['entry'], H) and id(e) not in lost]
        rs = []
        for e in act:
            st, r = st_fn(e, m)
            stats['pos_months'] += 1
            if st == 'ok':
                stats['pos_months_obs'] += 1; rs.append(r)
            else:
                lost.add(id(e))
                if st == 'spike':
                    stats['spike'] += 1
                elif bound == 'L':
                    rs.append(-1.0); stats['lost_L'] += 1
        if rs:
            out[m] = sum(rs) / len(rs)
        elif m in mkt:
            out[m] = mkt[m]; stats['months_empty'] += 1
    return out, stats


def e3_series(adds, bound, mkt, a, z):
    out, lost, stats = {}, set(), {'months_empty': 0, 'avg_n': []}
    for m in months(a, z):
        if m not in mkt:
            continue
        act = [e for e in adds if madd(m, -12) <= e['m'] < m and id(e) not in lost]
        rs = []
        for e in act:
            st, r = obs(e['t'], m, e['spell_start'])
            if st == 'ok':
                rs.append(r)
            else:
                lost.add(id(e))
                if st == 'missing' and bound == 'L':
                    rs.append(-1.0)
        if not rs:
            out[m] = mkt[m]; stats['months_empty'] += 1; continue
        w = len(rs) * W_UNIT
        stats['avg_n'].append(len(rs))
        out[m] = (mkt[m] - w * (sum(rs) / len(rs))) / (1 - w)
    stats['avg_n'] = round(sum(stats['avg_n']) / len(stats['avg_n']), 1) if stats['avg_n'] else None
    return out, stats


# ───────────────────────── 統計・判定 ─────────────────────────
def aftertax(s, turnover, a=200701, z=END, tax=0.20315):
    """日本の課税口座（一括・売却益課税）。毎年12月に片道回転率ぶんの含み益を実現・最後に全部売る"""
    V = B = 1.0
    for m in months(a, z):
        if m not in s:
            return None
        V *= 1 + s[m]
        if m % 100 == 12 and turnover > 0:
            f = min(1.0, turnover)
            T = tax * max(0.0, f * (V - B))
            V -= T
            B = (1 - f) * B + f * V
    return V - tax * max(0.0, V - B)


def evaluate(name, s, mkt, spy, turnover, cpu):
    s = {k: v for k, v in s.items() if k <= END}
    full = M.excess_stats(s, mkt)
    train = M.excess_stats(s, mkt, z=M.TRAIN_END)
    hold = M.excess_stats(s, mkt, a=M.HOLD_START)
    recent = M.excess_stats(s, mkt, a=M.RECENT_START)
    net = M.apply_cost(s, turnover, cpu)
    cost_hold = M.excess_stats(net, mkt, a=M.HOLD_START)
    roll = M.rolling(s, mkt, 20)
    dc = M.dca(s, mkt, 20)
    at_s, at_m = aftertax(s, turnover), aftertax(mkt, 0.0)
    pre_s = math.prod(1 + s[m] for m in months(M.HOLD_START, END) if m in s) if all(m in s for m in months(M.HOLD_START, END)) else None
    pre_m = math.prod(1 + mkt[m] for m in months(M.HOLD_START, END))
    return {'name': name, 'months': len(s), 'from': min(s) if s else None, 'full': full, 'train': train, 'hold': hold, 'recent': recent,
            'cost': {'turnover_oneway_per_year': turnover, 'cost_per_100pct': cpu}, 'net_hold': cost_hold,
            'rolling20': roll, 'dca20': dc,
            'vs_spy_hold': M.excess_stats(s, spy, a=M.HOLD_START),
            'jp_taxable_hold_lumpsum': ({'after_tax_ratio_vs_mkt': round(at_s / at_m, 3), 'pre_tax_ratio_vs_mkt': round(pre_s / pre_m, 3)}
                                        if at_s and pre_s else None)}


GORD = {'S': 0, 'A': 1, 'B': 2, 'C': 3}


def sgn(x):
    return None if x is None else (1 if x > 0 else -1)


def main():
    pre_sha = os.popen(f'git -C {M.BASE} log -n1 --format=%h -- out/{PRE}').read().strip()
    ff = M.ff_factors()
    mkt = {k: v for k, v in ff['mkt'].items() if k <= END}
    rf = ff['rf']
    spy = {k: v for k, v in M.yahoo('SPY').items() if k <= END}
    # ── 健全性 ──
    sanity = {'french_mkt_cagr_full': round(M.cagr(M.window(mkt, 192607, END)) * 100, 2),
              'french_mkt_cagr_2007': round(M.cagr(M.window(mkt, 200701, END)) * 100, 2),
              'spy_vs_mkt_1993': M.excess_stats(spy, mkt),
              'spy_mkt_corr': round(M.corr([spy[k] for k in sorted(set(spy) & set(mkt))], [mkt[k] for k in sorted(set(spy) & set(mkt))]), 4)}
    rows = load_membership()
    wiki, revid = load_wiki()
    sp = spells(rows)
    tested, series = [], {}

    # ── R: 実在のファンド ──
    fund_series = {}
    for nm, tk in {**FUNDS_R, **FUNDS_X}.items():
        r = {k: v for k, v in M.yahoo(tk).items() if k <= END}
        fund_series[nm] = r
        j = json.load(open(os.path.join(CACHE, f'yh_{tk}_1mo.json')))
        ndiv = len(((j['chart']['result'][0].get('events') or {}).get('dividends') or {}))
        ev = evaluate(nm, r, mkt, spy, 0.0, 0.001)
        ev.update({'family': 'primary_R' if nm in FUNDS_R else 'exploratory_X', 'primary': nm in FUNDS_R, 'ticker': tk,
                   'dividend_events': ndiv, 'bounded': False})
        tested.append(ev)
        series[nm] = r
    sanity['fund_dividend_events'] = {t['ticker']: t['dividend_events'] for t in tested}

    # ── E1 凍結 ──
    snaps = dict(rows)
    e1 = {}
    for nm, snap, start in (('E1a_frozen1996', '1996-01-02', 199601), ('E1b_frozen2007', '2006-12-29', 200701)):
        e1[nm] = {}
        for b in 'SL':
            s, info = frozen(snaps[snap], snap, start, sp, b)
            e1[nm][b] = (s, info)
    # 参考: 入れ替え続ける等加重（S のみ）と RSP
    upd = updated_ew(rows, sp, 199601, END)
    rsp = {k: v for k, v in M.yahoo('RSP').items() if k <= END}
    sanity['updated_ew_vs_rsp_2013'] = M.excess_stats(upd, rsp, a=201307)
    sanity['updated_ew_vs_rsp_2003'] = M.excess_stats(upd, rsp)

    # ── E2・E3 の出来事 ──
    rem, add = build_events(rows, wiki, sp)
    from collections import Counter
    ev_counts = {'removals': dict(Counter(e['cls'] for e in rem)), 'additions': dict(Counter(e['cls'] for e in add)),
                 'removals_by_period': {'<=2006': dict(Counter(e['cls'] for e in rem if e['m'] <= 200612)),
                                        '2007-2010': dict(Counter(e['cls'] for e in rem if 200701 <= e['m'] <= 201012)),
                                        '>=2011': dict(Counter(e['cls'] for e in rem if e['m'] >= 201101))},
                 'additions_by_period': {'<=2006': dict(Counter(e['cls'] for e in add if e['m'] <= 200612)),
                                         '2007-2010': dict(Counter(e['cls'] for e in add if 200701 <= e['m'] <= 201012)),
                                         '>=2011': dict(Counter(e['cls'] for e in add if e['m'] >= 201101))}}
    dels = [dict(e, entry=e['m']) for e in rem if e['cls'] in ('nonma', 'unknown')]
    dels_S = [e for e in dels if e['cls'] == 'nonma']
    e2 = {}
    for nm, H in (('E2a_deletions12', 12), ('E2b_deletions36', 36)):
        e2[nm] = {}
        for b, evs in (('S', dels_S), ('L', dels)):
            s, st = calendar_ew(evs, H, b, mkt, 199602, END, lambda e, m: obs(e['t'], m, e['spell_start']))
            e2[nm][b] = (s, st)
    adds_use = [e for e in add if e['cls'] in ('confirmed', 'unconfirmed')]
    e3 = {b: e3_series(adds_use, b, mkt, 199602, END) for b in 'SL'}
    # 参考: 入った社・外れた社そのもの（12か月・S のみ・判定なし）
    add_ev = [dict(e, entry=e['m']) for e in adds_use]
    adds_only, _ = calendar_ew(add_ev, 12, 'S', mkt, 199602, END, lambda e, m: obs(e['t'], m, e['spell_start']))

    # ── E4 スピンオフ ──
    spin, spin_cnt = load_spinoffs()
    e4 = {}
    if spin is not None:
        for b in 'SL':
            evs = spin if b == 'L' else [e for e in spin if e['obs']]

            def rf_(e, m):
                if not e['obs']:
                    return 'missing', None
                return obs(e['t'], m, e['entry'])
            e4[b] = calendar_ew(evs, 24, b, mkt, 199501, END, rf_)

    # ── 評価（上下限つき）──
    bounded = {**{k: v for k, v in e1.items()}, **e2, 'E3_mkt_minus_adds': e3}
    if e4:
        bounded['E4_spinoffs24'] = e4
    info_map = {}
    for nm, bs in bounded.items():
        tv, cpu = TURN[nm]
        evs = {}
        for b in 'SL':
            s, info = bs[b]
            ev = evaluate(f'{nm}__{b}', s, mkt, spy, tv, cpu)
            ev.update({'family': 'primary_E', 'primary': True, 'bound': b, 'bounded': True, 'coverage': info})
            evs[b] = ev
            series[f'{nm}__{b}'] = s
        info_map[nm] = evs
        tested += [evs['S'], evs['L']]

    # ── Holm（主の族）──
    pv = {}
    for t in tested:
        if not t['primary']:
            continue
        base = t['name'].split('__')[0]
        p = (t['hold'] or {}).get('p')
        if p is None:
            continue
        pv[base] = max(pv.get(base, 0), p)
    hp = M.holm(pv)

    # ── 判定 ──
    cands = []
    for t in tested:
        base = t['name'].split('__')[0]
        fam_p = hp.get(base) if t['primary'] else None
        g, c = M.grade(t['full'], t['train'], t['hold'], t['rolling20'], t['net_hold'], repl=None, family_holm_p=fam_p)
        t['grade'], t['criteria'], t['family_holm_p'] = g, c, fam_p
    for nm, evs in info_map.items():
        S_, L_ = evs['S'], evs['L']
        agree_h = sgn((S_['hold'] or {}).get('ex_ann')) == sgn((L_['hold'] or {}).get('ex_ann')) and S_['hold'] and L_['hold']
        tr_s, tr_l = S_['train'], L_['train']
        agree_t = (tr_s is None and tr_l is None) or (tr_s and tr_l and sgn(tr_s['ex_ann']) == sgn(tr_l['ex_ann']))
        if agree_h and agree_t:
            fg = max(S_['grade'], L_['grade'], key=lambda x: GORD[x])
        else:
            fg = '判定不能'
        cands.append({'name': nm, 'final_grade': fg, 'grade_S': S_['grade'], 'grade_L': L_['grade'],
                      'hold_ex_S': (S_['hold'] or {}).get('ex_ann'), 'hold_ex_L': (L_['hold'] or {}).get('ex_ann'),
                      'train_ex_S': (tr_s or {}).get('ex_ann'), 'train_ex_L': (tr_l or {}).get('ex_ann')})
    for t in tested:
        if not t['bounded']:
            cands.append({'name': t['name'], 'final_grade': t['grade'], 'hold_ex': (t['hold'] or {}).get('ex_ann'),
                          'train_ex': (t['train'] or {}).get('ex_ann'), 'family': t['family']})

    diag = {'E1a_vs_updated_ew_S_full': M.excess_stats(e1['E1a_frozen1996']['S'][0], upd),
            'E1a_vs_updated_ew_S_hold': M.excess_stats(e1['E1a_frozen1996']['S'][0], upd, a=M.HOLD_START),
            'E1b_vs_updated_ew_S_hold': M.excess_stats(e1['E1b_frozen2007']['S'][0], upd, a=M.HOLD_START),
            'updated_ew_S_vs_mkt_full': M.excess_stats(upd, mkt), 'updated_ew_S_vs_mkt_hold': M.excess_stats(upd, mkt, a=M.HOLD_START),
            'additions12_S_vs_mkt_full': M.excess_stats(adds_only, mkt), 'additions12_S_vs_mkt_hold': M.excess_stats(adds_only, mkt, a=M.HOLD_START),
            'note': '参考（判定なし）。S は観測できる社だけ＝生き残りの偏りで上に出やすい'}
    out = {'angle': 'index_events', 'prereg': PRE, 'prereg_commit': pre_sha, 'wiki_revid': revid,
           'sanity': sanity, 'event_counts': ev_counts, 'spinoff_counts': spin_cnt, 'holm_primary': hp,
           'candidates': cands, 'diagnostics': diag, 'tested': tested,
           'series': {k: {str(m): round(v, 5) for m, v in sorted(s.items())} for k, s in series.items()}}
    p = M.save('mw_index_events.json', out)
    print('書いた', p)
    for c in cands:
        print(c)


if __name__ == '__main__':
    if '--fetch-sec' in sys.argv:
        fetch_sec()
    elif '--fetch-yh' in sys.argv:
        fetch_yh()
    else:
        main()
