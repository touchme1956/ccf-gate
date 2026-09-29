#!/usr/bin/env python3
"""night/edge/fam_lmtext.py — 系統 lmtext（第10回 ①）: 決算書の文章（10-K の語の集計）の良い側（買いだけ・等加重） vs 同じ母集団の等加重

事前登録 out/edge_prereg_r10.json の families.lmtext（線・費用の原則・Holm の数え方は out/edge_prereg.json と同じ）。
  データ:
    ・Loughran-McDonald 10-X Summaries 1993-2025（sraf.nd.edu）＝全 10-K の語数・否定語・不確実語・訴訟語・ファイルの大きさの集計。
      本文は使わない・repo に入れない（CSV と縮めたキャッシュは out/_edge_cache＝gitignore）。
      様式は 10-K / 10-K405 / 10-KT（と 10-KT の405版 10KT405）の原本だけ。訂正（-A）と小型の 10-KSB は除く。
      ★覗き見の防止: 選定の段では **提出月 > SEL_END の提出を読み込みの時点で捨てる**（filings() の中）。
    ・CIK→ティッカー: SEC の company_tickers.json（今日の上場＝生き残りだけ）。1社に複数あれば表の最初（普通株）。'.'→'-'。
    ・株価: Yahoo の月次（adjclose＝配当込み／close＝分割調整済みの終値）。h.yahoo と同じ読み方・同じ h.guard を通す。
      ⚠ $1 未満の判定は当時の名目の株価で行う: Yahoo の close は後の分割で遡って割られているので、分割の記録（events=split）で戻す
      （例 AAPL 1998年の close は約 $0.3 だが当時の株価は $30 前後）。分割の記録は「当時の値札を復元する」ためだけに使い、選び方には使わない。
      そのため h.yahoo のキャッシュ（yh_<sym>.json・events なし）とは別名 yhs_<sym>.json で取る（中身の読み方は h.yahoo と同じ）。
  信号（良い側の向きは文献で固定・結果で決めない。どれも「低い側が良い」）:
    neg    否定語の割合 N_Negative/N_Words（Loughran & McDonald 2011）
    unc    不確実語の割合 N_Uncertainty/N_Words
    lit    訴訟語の割合 N_Litigious/N_Words
    dsize  |log(NetFileSize ÷ 前の 10-K)|（Cohen・Malloy・Nguyen の Lazy Prices の近似＝書き換えの少ない会社）
    dneg   否定語の割合の変化（今回−前回・符号つき）の小さい側＝悪化しない会社
    words  語数 N_Words（読みやすさ・Loughran & McDonald 2014）
    comp   6信号の順位（0〜1 の百分位）の平均。6信号すべてがそろう会社だけ
    「前の 10-K」＝同じ CIK の、今回の提出日の 9〜15か月前（274〜457日前）の提出のうち最も新しいもの。無ければ dsize・dneg は無い。
  規則: 月 m の組は m−1 月末までに提出された各社の最新の 10-K（提出月が m−15 以降）で決める。信号の低い側の三分位（または五分位）を
    等加重で持ち、毎月組み直す。変種 = 7信号 × 三分位/五分位 = 14。
  母集団（月 m）: 信号がある ∧ m−1 月末と m 月末の adjclose がある ∧ m−1 月末の名目株価 ≥ $1 ∧ 月 m のリターン ≤ +300%（分割の誤り）。
    ⚠ +300% の除外は月 m のリターンを見て落とす（事前登録どおり・データ誤りの掃除）。組と相手の両方から同じ会社を落とすので、どちらかだけを有利にはしない。
  相手（主）: 同じ月の母集団（その変種の信号がある生き残り）の等加重。French の米国市場との差は参考（run() の 'bench_mkt'）。
  費用: 片道の回転1あたり 0.25%（回転は組の入れ替わりから実測＝前月の重みを値動きで流した後から今月の等分へ）。
  選定期間: 1994-01〜2000-12（ret は 1994-01 から出す）。月の母集団が 100社未満の月は使わない（下の MIN_UNIV・事前登録に無い決め事）。
  判定の上限: 生き残りだけの価格なので線を全部越えても『候補』まで（事前登録 verdict_cap）。他の市場での再現は無し。

使い方: python3 night/edge/fam_lmtext.py --prefetch   → LM の縮約・ティッカー表・Yahoo の月次をキャッシュへ（全期間の生データを保存するだけ・読むのは guard 越し）
        python3 night/edge/fam_lmtext.py              → 変種の表（選定の段・2000-12 まで）
        python3 night/edge/fam_lmtext.py --save       → 選んで凍結（out/edge/spec_lmtext.json）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h
import csv, datetime, json, math, pickle, statistics as S, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

FAMILY = {
    'key': 'lmtext',
    'name': '決算書の文章（10-K の否定語・不確実語・訴訟語の割合、書き換えの量、否定語の悪化、語数の少ない側）',
    'implement': ('楽天証券の米国株（成長投資枠＝NISA 可・レバレッジではない）で、毎月、各社の直近の 10-K（年次報告書）の語の集計'
                  '（Loughran-McDonald の辞書で数えた否定語・不確実語・訴訟語の割合、前年からの大きさの変化、語数）で並べ、'
                  '良い側の3分の1（または5分の1）を等加重で持つ。組は数百〜千社になるので、個人は数十社へ絞る近似になる。'
                  'この信号をそのまま使う ETF は無い。⚠ 株価は今日上場している会社だけ（生き残り）なので、'
                  '線を全部越えても判定は『候補』まで（事前登録 r10 の verdict_cap）。他の市場での再現は無い'),
}

COST = 0.0025                     # 片道の回転1あたり（事前登録: 個別株の組）
START = 199401                    # 選定期間の始まり（事前登録: EDGAR の電子提出がそろってから）
MIN_UNIV = 100                    # 月の母集団（その変種の信号がある会社）の下限。事前登録に無い決め事（三分位で33社以上）
MAX_AGE = 15                      # 提出月が m−15 以降（提出から15か月以内）
PREV_DAYS = (274, 457)            # 前の 10-K の窓（9〜15か月前）
MAX_RET = 3.0                     # 月次リターン +300% 超はデータ誤りとして落とす
MIN_PX = 1.0                      # 前月末の名目株価 $1 未満の月は落とす
FORMS = {'10-K', '10-K405', '10-KT', '10KT405'}
SIGS = ['neg', 'unc', 'lit', 'dsize', 'dneg', 'words']
LM_URL = 'https://drive.usercontent.google.com/download?id=1nNoON97aL_6e9jZYZ38lUs-EO4kuMiCj&export=download&confirm=t'
TICK_URL = 'https://www.sec.gov/files/company_tickers.json'
YH_DAYS = 365                     # Yahoo のキャッシュの寿命（検定の段で取り直して値が変わらないように長め）

_MEMO = {}


# ───────────────────────── 読み込み ─────────────────────────
def _compact():
    """LM の CSV（188MB）を一度だけ読み、10-K の原本だけを {cik: [(提出日 YYYYMMDD, N_Words, N_Negative, N_Uncertainty, N_Litigious, NetFileSize)]} へ縮める。
    ⚠ キャッシュは全期間（生データの保存）。選定の段の切り落としは filings() で行う"""
    p = os.path.join(h.CACHE, 'lm_10k_compact.pkl')
    if os.path.exists(p):
        return pickle.load(open(p, 'rb'))
    raw = h.cached('lm_10x_summaries.csv', LM_URL, days=365)
    out = {}
    rd = csv.DictReader(raw.decode('latin-1').splitlines())
    for x in rd:
        if x['FORM_TYPE'].strip() not in FORMS:
            continue
        try:
            rec = (int(x['FILING_DATE']), int(x['N_Words']), int(x['N_Negative']), int(x['N_Uncertainty']),
                   int(x['N_Litigious']), int(x['NetFileSize']))
        except (ValueError, KeyError):
            continue
        out.setdefault(int(x['CIK']), []).append(rec)
    for v in out.values():
        v.sort()
    pickle.dump(out, open(p + '.part', 'wb'))
    os.replace(p + '.part', p)
    return out


def filings():
    """{cik: [提出の記録]}。★選定の段では提出月 > SEL_END の提出を捨てる（覗き見の防止）"""
    if 'fil' not in _MEMO:
        raw = _compact()
        cut = h.SEL_END if h.PHASE == 'select' else 999999
        _MEMO['fil'] = {c: [r for r in v if r[0] // 100 <= cut] for c, v in raw.items()}
        _MEMO['fil'] = {c: v for c, v in _MEMO['fil'].items() if v}
    return _MEMO['fil']


def tickers():
    """{cik: yahoo のティッカー}。今日の SEC の表＝生き残りだけ。1社に複数あれば表の最初の行"""
    if 'tk' not in _MEMO:
        sys.argv_saved = sys.argv; sys.argv = ['x']
        sys.path.insert(0, h.BASE)
        import hachimon_fetch as hf                    # SEC の User-Agent（メールは設定済み）
        sys.argv = sys.argv_saved
        p = os.path.join(h.CACHE, 'sec_company_tickers.json')
        if not (os.path.exists(p) and time.time() - os.path.getmtime(p) < 365 * 86400):
            b = urllib.request.urlopen(urllib.request.Request(TICK_URL, headers=hf.HDRS), timeout=60).read()
            open(p + '.part', 'wb').write(b)
            os.replace(p + '.part', p)
        d = json.load(open(p))
        out = {}
        for k in sorted(d, key=int):
            x = d[k]
            c = int(x['cik_str'])
            if c not in out:
                out[c] = x['ticker'].replace('.', '-')
        _MEMO['tk'] = out
    return _MEMO['tk']


def _yh_raw(sym):
    t0 = int(datetime.datetime(1970, 1, 1).timestamp())
    url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={t0}&period2={int(time.time())}'
           '&interval=1mo&events=split')
    p = os.path.join(h.CACHE, f'yhs_{sym}.json')
    if os.path.exists(p + '.none') and time.time() - os.path.getmtime(p + '.none') < YH_DAYS * 86400:
        return None                                          # 取れなかった記録（毎回取りに行かない）
    try:
        if os.path.exists(p) and time.time() - os.path.getmtime(p) < YH_DAYS * 86400:
            b = open(p, 'rb').read()
        else:
            b = None
            for a in range(3):
                try:
                    b = urllib.request.urlopen(urllib.request.Request(url, headers=h.UA), timeout=60).read()
                    break
                except urllib.error.HTTPError as e:
                    if e.code in (400, 404):
                        break
                    time.sleep(3 * (a + 1))
                except Exception:
                    time.sleep(3 * (a + 1))
            if b is None:
                open(p + '.none', 'w').write('')
                return None
            open(p + '.part', 'wb').write(b)
            os.replace(p + '.part', p)
        return json.loads(b)['chart']['result'][0]
    except Exception:
        return None


def prices(sym):
    """→ (adj {YYYYMM: 月末の adjclose}, nominal {YYYYMM: 月末の当時の名目終値})。h.yahoo と同じ月の付け方・h.guard 済み。取れなければ ({}, {})
    名目 = Yahoo の close（分割調整済み）× その月末より後の分割の比の積。分割の記録は当時の値札の復元にだけ使う"""
    res = _yh_raw(sym)
    if not res or not res.get('timestamp'):
        return {}, {}
    ind = res['indicators']
    adj = (ind.get('adjclose') or [{}])[0].get('adjclose') or []
    cl = ind['quote'][0].get('close') or []
    gmt = (res.get('meta') or {}).get('gmtoffset') or 0
    spl = sorted((v['date'], v['numerator'] / v['denominator']) for v in ((res.get('events') or {}).get('splits') or {}).values()
                 if v.get('denominator'))
    A, N = {}, {}
    now = datetime.date.today()
    cur = now.year * 100 + now.month                          # 今月の足はまだ月末ではない（途中の値）ので使わない
    for i, t in enumerate(res['timestamp']):
        d = datetime.datetime.utcfromtimestamp(t + gmt)
        m = d.year * 100 + d.month
        if m >= cur:
            continue
        a = adj[i] if i < len(adj) else None
        c = cl[i] if i < len(cl) else None
        if a is not None:
            A[m] = float(a)
        if c is not None:
            me = int(datetime.datetime(d.year + (d.month == 12), d.month % 12 + 1, 1).timestamp())   # 翌月初（月末の後）
            f = math.prod(r for (sd, r) in spl if sd >= me) if spl else 1.0
            N[m] = float(c) * f
    return h.guard(A), h.guard(N)


def load_prices(ciks):
    """{cik: (adj, nominal)}（取れた会社だけ）。Yahoo は6本の並列"""
    tk = tickers()
    todo = sorted(c for c in ciks if c in tk)

    def one(c):
        a, n = prices(tk[c])
        return c, (a, n) if a else None
    out = {}
    with ThreadPoolExecutor(6) as ex:
        for c, x in ex.map(one, todo):
            if x:
                out[c] = x
    return out, len(todo)


# ───────────────────────── 信号 ─────────────────────────
def _days(a, b):
    f = lambda x: datetime.date(x // 10000, x // 100 % 100, x % 100)
    return (f(b) - f(a)).days


def signals_of(recs):
    """1社の提出の列 → [(提出日, {信号: 値})]。前の 10-K は 274〜457日前のうち最も新しいもの（その時点で既に提出済み）"""
    out = []
    for i, (fd, nw, nn, nu, nl, sz) in enumerate(recs):
        if nw <= 0:
            continue
        s = {'neg': nn / nw, 'unc': nu / nw, 'lit': nl / nw, 'words': float(nw)}
        prev = None
        for j in range(i - 1, -1, -1):
            dd = _days(recs[j][0], fd)
            if dd > PREV_DAYS[1]:
                break
            if dd >= PREV_DAYS[0] and recs[j][1] > 0:
                prev = recs[j]
                break
        if prev is not None and prev[5] > 0 and sz > 0:
            s['dsize'] = abs(math.log(sz / prev[5]))
            s['dneg'] = nn / nw - prev[2] / prev[1]
        out.append((fd, s))
    return out


def state():
    """月ごとの信号・価格の材料（選定の段なら全部 SEL_END まで）"""
    if 'st' in _MEMO:
        return _MEMO['st']
    fil = filings()
    sig = {c: signals_of(v) for c, v in fil.items()}
    px, n_try = load_prices(set(sig))
    _MEMO['st'] = (sig, px, {'ciks_with_10k': len(sig), 'ciks_with_ticker': n_try, 'ciks_with_price': len(px)})
    return _MEMO['st']


def month_signals(sig, m):
    """月 m に使う各社の信号（m−1 月末までに提出・提出月が m−15 以降の最新の 10-K）"""
    last = h.add_months(m, -1)
    lo = h.add_months(m, -MAX_AGE)
    out = {}
    for c, lst in sig.items():
        best = None
        for fd, s in lst:
            fm = fd // 100
            if fm > last:
                break
            if fm >= lo:
                best = s
        if best is not None:
            out[c] = best
    return out


def build(spec):
    """spec: {'signal': neg|…|comp, 'q': 3|5} → (組 {m}, 相手 {m}, 回転 {m}, 組の社数 {m}, 母集団 {m})"""
    sig, px, _ = state()
    key, q = spec['signal'], spec['q']
    all_m = sorted({m for a, _ in px.values() for m in a})
    if not all_m:
        return {}, {}, {}, {}, {}
    months = [m for m in h.month_range(START, all_m[-1])]
    ret, bench, tv, npf, nun = {}, {}, {}, {}, {}
    prev_w = None                                            # 前月の組の重み（前月の値動きで流した後）
    for m in months:
        pm = h.add_months(m, -1)
        ms = month_signals(sig, m)
        rows = []
        for c, s in ms.items():
            if c not in px:
                continue
            A, N = px[c]
            if pm not in A or m not in A or A[pm] <= 0 or N.get(pm, 0) < MIN_PX:
                continue
            r = A[m] / A[pm] - 1
            if r > MAX_RET:
                continue
            rows.append((c, s, r))
        if key == 'comp':
            rows = [x for x in rows if all(k in x[1] for k in SIGS)]
            if len(rows) >= MIN_UNIV:
                n = len(rows)
                pct = {c: 0.0 for c, _, _ in rows}
                for k in SIGS:
                    srt = sorted(rows, key=lambda x: (x[1][k], x[0]))
                    for i, x in enumerate(srt):
                        pct[x[0]] += i / (n - 1)
                val = {c: pct[c] / len(SIGS) for c in pct}
        else:
            rows = [x for x in rows if key in x[1]]
            val = {c: s[key] for c, s, _ in rows}
        if len(rows) < MIN_UNIV:
            prev_w = None
            continue
        srt = sorted(rows, key=lambda x: (val[x[0]], x[0]))
        k = len(srt) // q
        pf = srt[:k]
        rr = {c: r for c, _, r in rows}
        w = {c: 1.0 / k for c, _, _ in pf}
        ret[m] = sum(rr[c] for c in w) / k
        bench[m] = sum(rr.values()) / len(rr)
        tv[m] = 0.0 if prev_w is None else 0.5 * sum(abs(w.get(c, 0.0) - prev_w.get(c, 0.0)) for c in set(w) | set(prev_w))
        npf[m], nun[m] = k, len(rows)
        g = {c: w[c] * (1 + rr[c]) for c in w}
        tot = sum(g.values())
        prev_w = {c: v / tot for c, v in g.items()} if tot > 0 else None
    return ret, bench, tv, npf, nun


def run(spec):
    mk, rf = h.us_market()
    ret, bench, tv, npf, nun = build(spec)
    return {'ret': ret, 'bench': bench, 'rf': rf, 'turnover': tv, 'cost': COST,
            'bench_mkt': {m: mk[m] for m in ret if m in mk}, 'n_portfolio': npf, 'n_universe': nun}


# ───────────────────────── 選定（2000-12 まで） ─────────────────────────
def variants():
    """成績を見る前に決めた変種（14本）＝7信号 × 三分位/五分位。向きは文献で固定（低い側）"""
    return [(f'{s}|q{q}', {'signal': s, 'q': q}) for s in SIGS + ['comp'] for q in (3, 5)]


def select():
    assert h.PHASE == 'select'
    mk, rf = h.us_market()
    rows = []
    for name, sp in variants():
        ret, bench, tv, npf, nun = build(sp)
        st = h.stats(ret, bench, rf, b=h.SEL_END, turnover=tv, cost=COST)
        stm = h.stats(ret, mk, rf, b=h.SEL_END, turnover=tv, cost=COST)
        stb = h.stats(bench, mk, rf, b=h.SEL_END)
        if not st:
            print(name, 'データ不足'); rows.append({'name': name, 'spec': sp, 'stats': None}); continue
        sub = {}
        for lab, a, b in (('1994-1997', 199401, 199712), ('1998-2000', 199801, h.SEL_END)):
            s2 = h.stats(ret, bench, rf, a=a, b=b, turnover=tv, cost=COST)
            sub[lab] = {'excess': s2['excess'], 't': s2['t']} if s2 else None
        tvy = round(sum(tv.values()) / len(tv) * 12, 2) if tv else None
        ex = [ret[m] - tv.get(m, 0.0) * COST - bench[m] for m in sorted(ret) if m <= h.SEL_END]
        t_raw = S.mean(ex) / (S.stdev(ex) / math.sqrt(len(ex)))     # 丸める前の t（h.stats は小数2桁に丸める＝同点の裁きに使う）
        rows.append({'name': name, 'spec': sp, 'stats': st, 't_raw': t_raw, 'sub': sub, 'turnover_yr': tvy,
                     'ex_vs_french_mkt': stm['excess'] if stm else None, 't_vs_french_mkt': stm['t'] if stm else None,
                     'bench_ex_vs_french_mkt': stb['excess'] if stb else None,
                     'n_portfolio_median': S.median(npf.values()), 'n_universe_median': S.median(nun.values())})
        print(f"{name:10} {st['from']}〜{st['to']} ex{st['excess']:+6.2f} t{st['t']:5.2f} (NW{st['t_nw']:5.2f}) "
              f"vol{st['vol']}/{st['bench_vol']} dd{st['maxdd']}/{st['bench_maxdd']} 回転{tvy}/年 "
              f"組{rows[-1]['n_portfolio_median']}/母{rows[-1]['n_universe_median']} 対French{rows[-1]['ex_vs_french_mkt']:+} 部分{sub}")
    return rows


# ───────────────────────── 先読みの検査 ─────────────────────────
def lookahead_test(spec, cut=199712):
    """別プロセスで EDGE_SEL_END=cut と 200012 の run() を回し、cut までの組・相手・回転が完全一致か
    （night/edge/prefix_check.py の 1990-12 の切り口はデータ（1993〜）より前で空回りするので、ここで 1997-12 でも切る）"""
    import subprocess
    code = ('import sys,json;sys.path.insert(0,%r);import fam_lmtext as f;'
            'r=f.run(json.loads(sys.argv[1]));print(json.dumps({k:r[k] for k in ("ret","bench","turnover")}))') % os.path.dirname(os.path.abspath(__file__))
    outs = {}
    for c in (cut, 200012):
        env = dict(os.environ, EDGE_PHASE='select', EDGE_SEL_END=str(c))
        p = subprocess.run([sys.executable, '-c', code, json.dumps(spec)], capture_output=True, text=True, env=env, timeout=7200)
        if p.returncode:
            raise RuntimeError(p.stderr[-800:])
        outs[c] = json.loads(p.stdout.strip().split('\n')[-1])
    a, b = outs[cut], outs[200012]
    res = {'cut': cut}
    for k in ('ret', 'bench', 'turnover'):
        ms = [m for m in a[k] if int(m) <= cut]
        bad = [m for m in ms if m not in b[k] or abs(a[k][m] - b[k][m]) > 1e-12]
        res[k] = {'months': len(ms), 'diffs': len(bad)}
    res['later_months_in_full'] = sum(1 for m in b['ret'] if int(m) > cut)
    res['ok'] = all(res[k]['diffs'] == 0 and res[k]['months'] > 0 for k in ('ret', 'bench', 'turnover'))
    return res


LOOKAHEAD = ('(1) 別プロセスの切り口: EDGE_SEL_END=199712 と 200012 で別々に run() を回し、1997-12 までの組・相手・回転が完全一致（1e-12）。'
             '（night/edge/prefix_check.py の 1990-12 の切り口は LM のデータ（1993〜）より前なので比べる月が0か月＝空回り。1997-12 でも切った）'
             '(2) 読み込みの切り落とし: 選定の段では LM の提出を「提出月 > SEL_END」で捨て、株価は h.guard（月 > SEL_END を捨てる）。'
             '(3) 月合わせ（コードを読む検査）: 月 m の組は m−1 月末までに提出された 10-K（提出月 ≤ m−1）の信号と m−1 月末の名目株価で決め、'
             '月 m のリターンは m−1 月末→m 月末の adjclose。前の 10-K は今回の提出より前の提出だけ。順位・分位は同じ月の断面の中だけで作り、'
             '全期間の平均・分位は一切使わない。⚠ 例外は事前登録の +300% の除外（月 m のリターンで落とす）＝組と相手の両方から同じ会社を落とす。'
             '(4) 分割の記録は Yahoo の遡った割り算を戻して当時の名目株価（$1 の線）を復元するためだけに使う（今日時点の記録を使うが、復元される値は当時の値札）')


# ───────────────────────── 凍結 ─────────────────────────
def main(save=False):
    rows = select()
    ok = [r for r in rows if r['stats']]
    elig = [r for r in ok if r['stats']['excess'] >= 1.0]
    if elig:
        best = max(elig, key=lambda r: r['t_raw'])
        how = '事前登録どおり（選定期間の費用後の超過が +1%/年以上の変種の中で、費用後の超過の t が最大）'
    else:
        best = max(ok, key=lambda r: r['t_raw'])
        how = 'どの変種も +1%/年 に届かなかった。t が最大の変種を選んだ（線に届かないことを承知で・事前登録の選び方の但し書きどおり）'
    spec = dict(best['spec'])
    spec.update({'start': START, 'min_univ': MIN_UNIV, 'max_age_months': MAX_AGE, 'prev_days': list(PREV_DAYS),
                 'max_ret': MAX_RET, 'min_px': MIN_PX, 'forms': sorted(FORMS), 'side_note': '低い側（文献の向きで固定）'})
    _, _, info = state()
    st = best['stats']
    tbl = [{'name': x['name'], 'excess': x['stats']['excess'] if x['stats'] else None, 't': x['stats']['t'] if x['stats'] else None,
            't_nw': x['stats']['t_nw'] if x['stats'] else None, 'from': x['stats']['from'] if x['stats'] else None,
            'vol': x['stats']['vol'] if x['stats'] else None, 'bench_vol': x['stats']['bench_vol'] if x['stats'] else None,
            'maxdd': x['stats']['maxdd'] if x['stats'] else None, 't_unrounded': x.get('t_raw'), 'sub_periods': x.get('sub'), 'turnover_yr': x.get('turnover_yr'),
            'ex_vs_french_mkt': x.get('ex_vs_french_mkt'), 't_vs_french_mkt': x.get('t_vs_french_mkt'),
            'n_portfolio_median': x.get('n_portfolio_median'), 'n_universe_median': x.get('n_universe_median')} for x in rows]
    print('選んだ:', best['name'], how)
    print('選定期間:', st)
    print('材料:', info)
    if not save:
        return best
    la = lookahead_test(spec)
    print('lookahead', la)
    assert la['ok'], la
    others = sorted(ok, key=lambda x: -x['stats']['t'])[:4]
    sub = best['sub']
    rationale = (
        f'【規則】{best["name"]}: 米国上場の生き残りの会社（SEC の今日のティッカー表 × Yahoo の株価）を、毎月 m−1 月末までに出た直近の 10-K の'
        f'「{spec["signal"]}」で並べ、低い側の{"三" if spec["q"] == 3 else "五"}分位を等加重で持つ（毎月組み直す）。相手は同じ月の同じ母集団の等加重。'
        '【なぜ】2001年より前に筋があった・または同じ筋の文献: 否定語の多い 10-K は悪い知らせを含み市場はそれをゆっくり織り込む'
        '（Tetlock 2007・Loughran & McDonald 2011）、長く読みにくい 10-K は悪い知らせを隠す（Li 2008「Annual report readability」・Loughran & McDonald 2014）、'
        '書き換えの多い 10-K は事業の変化を示し、投資家は去年からの変更を読み飛ばす（Cohen・Malloy・Nguyen 2020「Lazy Prices」）。'
        '⚠ これらの論文はどれも2001年より後の公表で、辞書（LM）も2011年の作。使う10-K の本文そのものは当時に公開されていた。'
        f'【選定期間 {st["from"]}〜{st["to"]}（{st["years"]}年）】費用後の年率 {st["cagr"]}% 対 同じ母集団の等加重 {st["bench_cagr"]}%、'
        f'超過 {st["excess"]:+}%/年、t {st["t"]}（Newey-West {st["t_nw"]}）、ぶれ {st["vol"]}% 対 {st["bench_vol"]}%、'
        f'最大下落 {st["maxdd"]}% 対 {st["bench_maxdd"]}%。部分期間 1994-1997 {sub["1994-1997"]["excess"]:+}%/年（t {sub["1994-1997"]["t"]}）・'
        f'1998-2000 {sub["1998-2000"]["excess"]:+}%/年（t {sub["1998-2000"]["t"]}）。回転 {best["turnover_yr"]}/年（実測）。'
        f'French の米国市場に対しては {best["ex_vs_french_mkt"]:+}%/年（t {best["t_vs_french_mkt"]}・参考）'
        f'——同じ母集団の等加重そのものが French 市場に {best["bench_ex_vs_french_mkt"]:+}%/年（生き残りだけの等加重は市場より強く出る）。'
        f'【選び方】{how}。t の上位4: ' + ' / '.join(f'{x["name"]} {x["stats"]["excess"]:+}%（t {x["stats"]["t"]}）' for x in others) + '。'
        f'【材料】LM の 10-K の原本（{"・".join(sorted(FORMS))}）がある CIK {info["ciks_with_10k"]}社（選定の段＝2000-12 までに提出）、'
        f'そのうち今日の SEC のティッカー表に載る {info["ciks_with_ticker"]}社、Yahoo の月次が取れた {info["ciks_with_price"]}社'
        '（取れなかった会社はただ居ない）。組の社数の中央値 ' + str(best['n_portfolio_median']) + '・母集団 ' + str(best['n_universe_median']) + '。'
        '【判定の上限】⚠ 生き残りだけの価格（上場廃止した会社が入らない）なので、線を全部越えても『候補』まで（事前登録 r10 verdict_cap）。他の市場での再現は無し。'
        '【事前登録に無かった決め事】(a) 月の母集団 100社未満の月は使わない（1994年初めの EDGAR の移行期）。(b) 10-KT の405版（10KT405）も 10-KT として含めた。'
        '(c) 前の 10-K の「9〜15か月前」は 274〜457日。(d) dneg は符号つきの変化（今回−前回）の低い側＝否定語が減った会社。'
        '(e) comp は6信号がすべてそろう会社の中で各信号を百分位にして平均。(f) $1 の線は分割の記録で戻した当時の名目株価で判定。'
        '(g) Yahoo は h.yahoo と同じ読み方だが分割の記録を得るため別のキャッシュ名（yhs_）で取った。(h) 1社に複数のティッカーがあれば SEC の表の最初。'
        '(i) 回転は初月を0（他の系統と同じ）。'
        '(j) t の比較は h.stats の小数2桁に丸める前の値で行った（dneg の三分位と五分位が丸めると同じ t 0.36 で並んだため。丸める前は '
        + ' / '.join(f'{x["name"]} {x["t_raw"]:.5f}' for x in ok if x['spec']['signal'] == spec['signal']) + '）。'
        '⚠ 選定期間は7年と短い（事前登録にも明記）。'
    )
    extra = {'implement': FAMILY['implement'], 'family_name': FAMILY['name'], 'lookahead_test': LOOKAHEAD,
             'lookahead_result': la, 'variants_table': tbl, 'selection_note': how, 'data_counts': info,
             'verdict_cap': '候補まで（生き残りだけの価格・事前登録 r10）',
             'benchmark': '主＝同じ月の同じ母集団（その変種の信号がある生き残りの会社）の等加重（run() の bench）。参考＝French 米国市場（run() の bench_mkt）',
             'cost_note': '片道の回転100%につき0.25%。回転は前月の組を値動きで流した重みから今月の等分への入れ替わり（実測）'}
    doc = h.save_spec('lmtext', spec, rationale, len(rows), st, extra)
    print('凍結:', best['name'], doc['n_variants_tried'])
    return doc


def prefetch():
    """生データをキャッシュへ（全期間。読むのは filings()/prices() の guard 越しだけ）"""
    raw = _compact()
    tk = tickers()
    ciks = sorted(c for c in raw if c in tk)
    print('LM 10-K の CIK', len(raw), '・ティッカーあり', len(ciks), flush=True)
    done = [0, 0]

    def one(c):
        r = _yh_raw(tk[c])
        done[0] += 1
        done[1] += r is not None
        if done[0] % 250 == 0:
            print(done, flush=True)
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(one, ciks))
    print('取れた', done, flush=True)


if __name__ == '__main__':
    if '--prefetch' in sys.argv:
        prefetch()
    else:
        main(save='--save' in sys.argv)
