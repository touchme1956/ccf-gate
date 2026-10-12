#!/usr/bin/env python3
"""night/bestpf_persistence13f.py — bestpf の R2b（読むだけ・門の判定・採点・配分には不使用）

問い（事前登録 out/bestpf_prereg.json の modules.R2_elite_clone.R2b_persistence・コミット 7c4b672）:
  13F の『全提出者』の中で、過去3年の成績が上位10%だった運用者は、その後の1年も勝つか。
  上位10%の運用者の保有を人ごとに等しくまとめて翌年持つと、SPY（配当込み）に勝つか。下位10%も対照で。
  過去3年の順位と翌年の順位の順位相関（毎年の値と平均）。

作り方（事前登録が許した軽い形＝各年の第4四半期〔12月末の報告期間〕だけ）:
  - 13F データセット（SEC の四半期 zip）の 12月末の 13F-HR（2月末の数日前までに提出された最後の原本）を
    night/mw_best_ideas_13f.read_clean で読む（単位・株数の掃除はその道具と同じ単一の実装）
  - 運用者の線は mw_best_ideas_13f と同じ: 受動的な名前を除く・株の銘柄数 10〜500・ETF 等の比重 ≤20%・銀行／保険を除く
  - 各運用者の『翌年の成績』: 12月末の保有（比重＝13F の価額の比）を、提出の翌々月の初め（3月初め）から翌年の2月末まで
    買って持つ（期間内は比重が漂う）配当込みのリターン（Yahoo の月次・分割と配当を調整した終値）。
    記号は FTD（当時の記号）と OpenFIGI（現在の記号）の候補を、13F の当時の株価と ±15% で照合して決める（その道具の resolve）
  - 価格が取れる比重が80%未満の運用者はその年は外す（外した数を出す）。組む前に取引が終わった株（gone_before）は買えないので
    分母から除く。期中に価格が途切れた株は O（観測できる分で按分）と P30（最初の欠けた月に −30%・以後は現金）の二本で囲む
  - 過去3年の成績＝その前の3年の『翌年の成績』の複利（3年ともそろう運用者だけ）。上位10%・下位10%
  - 上位10%のかご＝その運用者たちに同じ金額を配り、各自の保有を1年持つ（＝運用者の年リターンの単純平均・月次は価値で加重）

段
  --fetch : 12月末の 13F データセット zip と FTD（CUSIP→当時の記号）を取る → out/_mw_cache/bi13f/（その道具と共有）
  --parse : 各年の 12月末の保有（運用者ごとの全保有）→ out/_bestpf_cache/persistence13f/h_{yyyymm}.json
  --map   : 全保有の CUSIP を記号へ（FTD → Yahoo 照合 → 残りを OpenFIGI → もう一度照合）→ resolved.json
  (既定)  : 計算して out/bestpf_persistence13f.json を書く
"""
import datetime, json, math, os, sys, time
import statistics as S
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402
import mw_best_ideas_13f as B  # noqa: E402

BASE = M.BASE
C = os.path.join(BASE, 'out', '_bestpf_cache', 'persistence13f')
OUT = os.path.join(BASE, 'out', 'bestpf_persistence13f.json')
PREREG_COMMIT = '7c4b672'
YEARS = list(range(2013, 2026))          # 12月末の報告期間（2012-12 は SEC の構造化データセットが無い）
PERIODS = [y * 100 + 12 for y in YEARS]
COVER_MIN = 0.80                         # 価格が取れる比重の下限（事前登録）
LOOKBACK = 3                             # 過去3年（事前登録）
TOP_FRAC = 0.10                          # 上位10%（事前登録）
MISS_P30 = -0.30
COST_ONEWAY = 0.002                      # R2 の費用（片道 0.2%）
FTD_FROM, FTD_TO = 201312, 202609


def hold_months(p):
    """12月末の報告 p → 3月〜翌年2月の12か月（提出の翌々月の初めから）"""
    f = B.madd(p, 2)                     # 2月（期限月）
    return [B.madd(f, i) for i in range(1, 13)]


# ───────────────────────── 取得 ─────────────────────────
def fetch():
    import re
    os.makedirs(B.C, exist_ok=True)
    hrefs = B.links(B.PAGE_13F, 'page_13f.html', r'href="([^"]*form13f\.zip)"')
    got = {}
    for p in PERIODS:
        h = B.zip_for_period(p, hrefs)
        if not h:
            print('!! 期間', p, 'の zip が無い'); got[p] = None; continue
        path = os.path.join(B.C, h.rsplit('/', 1)[-1])
        B.sec_get('https://www.sec.gov' + h, path)
        got[p] = os.path.basename(path)
        print(p, '→', got[p], os.path.getsize(path) // 1_000_000, 'MB', flush=True)
    ftd = B.links(B.PAGE_FTD, 'page_ftd.html', r'href="([^"]*cnsfails(\d{6})[ab]\.zip)"')
    os.makedirs(os.path.join(B.C, 'ftd'), exist_ok=True)
    n = 0
    for h, ym in ftd:
        if FTD_FROM <= int(ym) <= FTD_TO:
            B.sec_get('https://www.sec.gov' + h, os.path.join(B.C, 'ftd', h.rsplit('/', 1)[-1]))
            n += 1
    print('FTD', n, '本', flush=True)
    json.dump(got, open(os.path.join(C, 'zips.json'), 'w'))


# ───────────────────────── 12月末の保有を読む ─────────────────────────
def parse_one(p):
    outp = os.path.join(C, f'h_{p}.json')
    if os.path.exists(outp):
        return
    hrefs = B.links(B.PAGE_13F, 'page_13f.html', r'href="([^"]*form13f\.zip)"')
    h = B.zip_for_period(p, hrefs)
    zn = h.rsplit('/', 1)[-1] if h else None
    if not zn:
        print('!! zip なし', p); return
    t0 = time.time()
    R = B.read_clean(p, os.path.join(B.C, zn))
    mult = 1000 if p <= 202209 else 1        # 13F の価額は 2022-09 の報告まで千ドル単位
    clean, shs, etfv, cover, acc2cik = R['clean'], R['shs'], R['etfv'], R['cover'], R['acc2cik']
    excl = Counter(); mgrs = []
    for a, d in clean.items():
        cik = acc2cik[a]
        nm = cover.get(a, {}).get('FILINGMANAGER_NAME', '')
        sv = sum(d.values()); ev = etfv.get(a, 0.0); n = len(d)
        if sv <= 0:
            excl['no_stock'] += 1; continue
        why = None
        if B.PASSIVE_RE.search(nm):
            why = 'passive_name'
        elif n < B.NMIN:
            why = 'n_lt_10'
        elif n > B.NMAX:
            why = 'n_gt_500'
        elif ev / (sv + ev) > B.ETF_SHARE_MAX:
            why = 'etf_share'
        elif not B.eligible({'name': nm}):
            why = 'bank_insurance'
        if why:
            excl[why] += 1; continue
        mgrs.append({'cik': cik, 'acc': a, 'name': nm, 'n': n, 'value_usd': round(sv * mult), 'etf_share': round(ev / (sv + ev), 4),
                     'w': {cu: round(v / sv, 8) for cu, v in d.items()}})
    # 照合に使う当時の株価（$）: 全提出者の合意（3社以上の中央値）→ 無ければ持ち手の暗黙の株価の中央値
    need = {cu for m in mgrs for cu in m['w']}
    ipx = defaultdict(list)
    for m in mgrs:
        a = m['acc']
        for cu in m['w']:
            sh = shs.get((a, cu))
            if sh:
                ipx[cu].append(clean[a][cu] * mult / sh)
    sec = {}
    for cu in need:
        px = R['cons'][cu] * mult if cu in R['cons'] else (S.median(ipx[cu]) if ipx[cu] else None)
        sec[cu] = {'px_usd': round(px, 4) if px else None, 'holders_all': len(R['px'].get(cu, [])),
                   'agg_usd': round(R['agg'].get(cu, 0) * mult), 'name': R['names'][cu].most_common(1)[0][0] if R['names'][cu] else '',
                   'title': R['titles'][cu].most_common(1)[0][0] if R['titles'][cu] else ''}
    for m in mgrs:
        del m['acc']
    out = {'period': p, 'zip': zn, 'cutoff': R['cut'], 'unit_mult': mult, 'n_filings': len(R['best']),
           'n_eligible': len(mgrs), 'excluded': dict(excl), 'fix': dict(R['fix']), 'managers': mgrs, 'sec': sec}
    tmp = outp + '.tmp'
    json.dump(out, open(tmp, 'w')); os.replace(tmp, outp)
    print(p, 'filings', len(R['best']), 'eligible', len(mgrs), 'excl', dict(excl), 'CUSIP', len(sec), f'{time.time() - t0:.0f}s', flush=True)


def parse():
    import multiprocessing as mp
    with mp.Pool(2) as pool:
        pool.map(parse_one, PERIODS, chunksize=1)


def load_h(p):
    pth = os.path.join(C, f'h_{p}.json')
    return json.load(open(pth)) if os.path.exists(pth) else None


# ───────────────────────── CUSIP → 記号 ─────────────────────────
def build_ftd(cs):
    """FTD（決済の失敗の公表データ・半月ごと）から CUSIP ごと・月ごとの当時の記号・終値・名前（mw_best_ideas_13f.build_ftd と同じ読み方・
    書き先だけ自分のキャッシュ）"""
    import zipfile
    out = defaultdict(dict)
    fd = os.path.join(B.C, 'ftd')
    for fn in sorted(os.listdir(fd)):
        if not fn.endswith('.zip'):
            continue
        z = zipfile.ZipFile(os.path.join(fd, fn))
        txt = z.read(z.namelist()[0]).decode('latin-1')
        for line in txt.splitlines()[1:]:
            parts = line.split('|')
            if len(parts) < 6:
                continue
            cu = B.norm_cusip(parts[1])
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
    print('FTD: 候補', len(cs), '→ FTD に出た', len(js), flush=True)
    return js


def all_tasks():
    """(CUSIP, 期間) → 照合に使う当時の株価。重み（全運用者の比重の合計）も返す＝OpenFIGI に回す順番"""
    tasks, wsum = {}, defaultdict(float)
    for p in PERIODS:
        H = load_h(p)
        if not H:
            continue
        for m in H['managers']:
            for cu, w in m['w'].items():
                wsum[(cu, p)] += w
        for cu, v in H['sec'].items():
            tasks[(cu, p)] = v['px_usd']
    return tasks, wsum


def do_map():
    tasks, wsum = all_tasks()
    cs = {k[0] for k in tasks}
    print('(CUSIP, 期間)', len(tasks), '・CUSIP', len(cs), flush=True)
    pth = os.path.join(C, 'ftd_index.json')
    ftd = json.load(open(pth)) if os.path.exists(pth) else build_ftd(cs)
    figi = B.load_figi()
    tasks = {k: v for k, v in tasks.items() if v}
    rp = os.path.join(C, 'resolved.json')
    done = {}
    if os.path.exists(rp):
        done = {(k.split('|')[0], int(k.split('|')[1])): v for k, v in json.load(open(rp)).items()}
    todo = {k: v for k, v in tasks.items() if not done.get(k)}
    print('照合 1回目（FTD と既存の OpenFIGI）', len(todo), flush=True)
    res = B.resolve(todo, None, ftd, figi, fetch=True, threads=6)
    done.update(res)
    json.dump({f'{k[0]}|{k[1]}': v for k, v in done.items()}, open(rp, 'w'))
    # 照合できなかった CUSIP を OpenFIGI へ（重みの大きい順）
    wcu = defaultdict(float)
    for (cu, _), w in wsum.items():
        wcu[cu] += w
    left = sorted({k[0] for k, v in done.items() if not v and k in tasks}, key=lambda cu: -wcu[cu])
    left = [cu for cu in left if cu not in figi]
    print('OpenFIGI へ', len(left), flush=True)
    if '--no-figi' not in sys.argv and left:
        figi = B.figi_map(set(left))
        todo = {k: v for k, v in tasks.items() if not done.get(k) and (figi.get(k[0]) or {}).get('ticker')}
        print('照合 2回目（OpenFIGI の記号）', len(todo), flush=True)
        res = B.resolve(todo, None, ftd, figi, fetch=True, threads=6)
        done.update({k: v for k, v in res.items() if v})
        json.dump({f'{k[0]}|{k[1]}': v for k, v in done.items()}, open(rp, 'w'))
    ok = sum(1 for v in done.values() if v)
    wt = sum(wsum.values()); wok = sum(w for k, w in wsum.items() if done.get(k))
    print('照合できた', ok, '/', len(done), f'・比重で {wok / wt:.3f}', flush=True)


# ───────────────────────── 計算 ─────────────────────────
def load_resolved():
    j = json.load(open(os.path.join(C, 'resolved.json')))
    return {(k.split('|')[0], int(k.split('|')[1])): v for k, v in j.items()}


_compact = {}


def sym_data(sym):
    """Yahoo の月次から、検証の窓（2014-02〜）の配当込みリターンと、組む月（2月末）に値があるかだけを残す（メモリ節約）"""
    if sym in _compact:
        return _compact[sym]
    y = B.yh_load(sym)
    out = None
    if y is not None:
        out = {'ret': {m: r for m, r in y['ret'].items() if m >= 201403},
               'adj_ok': {m for m in y['adj'] if m % 100 == 2 and m >= 201402},
               'later': sorted(m for m in y['adj'] if m >= 201402),
               'spike': y['spike']}
    B._yh.pop(sym, None)
    _compact[sym] = out
    return out


def status(cu, p, res):
    """mw_best_ideas_13f.status と同じ判定（ok / unmapped / gone_before）を、メモリを食わない形で"""
    sym = res.get((cu, p))
    if not sym:
        return 'unmapped', None
    y = sym_data(sym)
    f = B.formation(p)
    if y is None:
        return 'unmapped', None
    if f not in y['adj_ok'] or (y['spike'] and y['spike'] <= f):
        later = [k for k in y['later'] if f < k <= B.madd(f, 3)]
        return ('unmapped', None) if later else ('gone_before', None)
    return 'ok', y


def manager_year(w, st, ms, L):
    """1人の運用者の1年（12か月）を買って持つ。w={cu: 比重}・st={cu:(status, data)}。
    L=None → O（観測できる分で按分・途切れた株は外して按分し直す）／ L=数値 → 未観測は最初の月に L・以後は現金。
    → (月次リターン {m: r}, 価格が取れる比重の割合, 組む前に終わった比重)"""
    gone = sum(x for cu, x in w.items() if st[cu][0] == 'gone_before')
    live = {cu: x for cu, x in w.items() if st[cu][0] != 'gone_before'}
    tot = sum(live.values())
    if tot <= 0:
        return None, 0.0, gone
    okw = sum(x for cu, x in live.items() if st[cu][0] == 'ok')
    cover = okw / tot
    v = {cu: x / (okw if L is None else tot) for cu, x in live.items() if (L is not None or st[cu][0] == 'ok')}
    cash = 0.0
    out = {}
    for m in ms:
        if m > B.END:
            break
        V0 = sum(v.values()) + cash
        if V0 <= 0:
            break
        newv = {}
        if L is None:
            obs = {cu: st[cu][1]['ret'][m] for cu in v if m in st[cu][1]['ret']}
            base = sum(v[cu] for cu in obs)
            if base <= 0:
                out[m] = 0.0           # 観測できる株が尽きた＝現金（まれ・数える）
                v = {}; cash = V0
                continue
            R = sum(v[cu] * r for cu, r in obs.items()) / base
            newv = {cu: v[cu] * (1 + obs[cu]) for cu in obs}
            sc = (V0 - cash) * (1 + R) / sum(newv.values()) if sum(newv.values()) > 0 else 0
            v = {cu: x * sc for cu, x in newv.items()}
            out[m] = ((V0 - cash) * (1 + R) + cash) / V0 - 1
        else:
            for cu, x in v.items():
                r = st[cu][1]['ret'].get(m) if st[cu][0] == 'ok' else None
                if r is None:
                    cash += x * (1 + L)
                else:
                    newv[cu] = x * (1 + r)
            v = newv
            out[m] = (sum(v.values()) + cash) / V0 - 1
    return out, cover, gone


def comp(rs):
    g = 1.0
    for r in rs:
        g *= 1 + r
    return g - 1


def ranks(x):
    """平均順位（同順位は平均）"""
    idx = sorted(range(len(x)), key=lambda i: x[i])
    r = [0.0] * len(x)
    i = 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and x[idx[j + 1]] == x[idx[i]]:
            j += 1
        for k in range(i, j + 1):
            r[idx[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(a, b):
    if len(a) < 10:
        return None
    return M.corr(ranks(a), ranks(b))


def t_simple(x):
    if len(x) < 3:
        return None
    sd = S.stdev(x)
    return S.mean(x) / (sd / math.sqrt(len(x))) if sd > 0 else None


def nw_t_small(x, lag=1):
    """年次の少ない点の Newey-West（Bartlett・lag 1）。点が少ないので参考"""
    n = len(x)
    if n < 4:
        return None
    m = S.mean(x); e = [v - m for v in x]
    s_ = sum(v * v for v in e) / n
    for L_ in range(1, lag + 1):
        s_ += 2 * (1 - L_ / (lag + 1)) * sum(e[i] * e[i - L_] for i in range(L_, n)) / n
    return m / math.sqrt(s_ / n) if s_ > 0 else None


def basket_monthly(series_list):
    """同じ金額を配った運用者たち（各自の月次リターン）→ かごの月次リターン（価値で加重＝1年後は単純平均と一致）"""
    vals = [1.0] * len(series_list)
    ms = sorted({m for s_ in series_list for m in s_})
    out = {}
    for m in ms:
        V0 = sum(vals)
        for i, s_ in enumerate(series_list):
            vals[i] *= 1 + s_.get(m, 0.0)
        out[m] = sum(vals) / V0 - 1
    return out


def agg_weights(mgr_ws):
    """運用者ごとの比重（価格が取れる株で合計1）を人ごとに等しく足す → {cu: 比重}"""
    out = defaultdict(float)
    k = len(mgr_ws)
    for w in mgr_ws:
        for cu, x in w.items():
            out[cu] += x / k
    return dict(out)


def turnover(a, b):
    keys = set(a) | set(b)
    return 0.5 * sum(abs(a.get(k, 0) - b.get(k, 0)) for k in keys)


def compute_years():
    """→ yearly[p] = {cik: {'O': {m:r}, 'P30': {m:r}, 'cover', 'gone', 'w_ok': {cu: 比重}, 'name', 'value_usd'}} と各年の数"""
    res = load_resolved()
    yearly, counts, secinfo = {}, {}, {}
    for p in PERIODS:
        H = load_h(p)
        if not H:
            continue
        ms = hold_months(p)
        cus = set(H['sec'])
        st = {cu: status(cu, p, res) for cu in cus}
        sc = Counter(v[0] for v in st.values())
        yr, cnt = {}, Counter()
        for m in H['managers']:
            w = m['w']
            o, cov, gone = manager_year(w, st, ms, None)
            if o is None:
                cnt['no_live'] += 1; continue
            if cov < COVER_MIN:
                cnt['cover_lt_80'] += 1; continue
            p30, _, _ = manager_year(w, st, ms, MISS_P30)
            okw = {cu: x for cu, x in w.items() if st[cu][0] == 'ok'}
            t_ = sum(okw.values())
            yr[m['cik']] = {'O': o, 'P30': p30, 'cover': cov, 'gone': gone, 'name': m['name'], 'value_usd': m['value_usd'],
                            'n': m['n'], 'w_ok': {cu: x / t_ for cu, x in okw.items()}}
            cnt['kept'] += 1
        cnt['eligible'] = len(H['managers'])
        yearly[p] = yr
        counts[p] = {'filings': H['n_filings'], 'eligible': H['n_eligible'], 'excluded_by_line': H['excluded'],
                     'kept_cover80': cnt['kept'], 'dropped_cover_lt_80': cnt['cover_lt_80'], 'dropped_no_live': cnt['no_live'],
                     'cusip_status': dict(sc),
                     'months': [m for m in ms if m <= B.END]}
        secinfo[p] = {cu: (res.get((cu, p)), H['sec'][cu]['name']) for cu in cus}
        print(p, counts[p]['kept_cover80'], '/', counts[p]['eligible'], 'cover<80', cnt['cover_lt_80'], dict(sc), flush=True)
    return yearly, counts, secinfo


def window_ret(r, ms):
    xs = [r.get(m) for m in ms]
    return comp(xs) if all(x is not None for x in xs) else None


def main():
    yearly, counts, secinfo = compute_years()
    spy = M.yahoo('SPY'); qqq = M.yahoo('QQQ')
    ps = sorted(yearly)
    ann = {p: {cik: comp([d['O'][m] for m in sorted(d['O'])]) for cik, d in yearly[p].items()} for p in ps}
    full_years = {p: len(counts[p]['months']) == 12 for p in ps}
    rows = []
    top_series, bot_series, all_series, top_series_p30, bot_series_p30 = {}, {}, {}, {}, {}
    sens = defaultdict(dict)
    prev_top_w = None
    turns = []
    for i, p in enumerate(ps):
        past = [p - 100 * k for k in range(LOOKBACK, 0, -1)]      # 例: 2016-12 の保有なら 2013-12・2014-12・2015-12 の翌年の成績
        if any(q not in ann for q in past):
            continue
        cur = yearly[p]
        score = {}
        for cik in cur:
            xs = [ann[q].get(cik) for q in past]
            if all(x is not None for x in xs):
                score[cik] = comp(xs)
        ciks = sorted(score, key=lambda c: -score[c])
        n = len(ciks)
        k = max(1, math.ceil(n * TOP_FRAC))
        top, bot = ciks[:k], ciks[-k:]
        ms = counts[p]['months']
        spy_r = window_ret(spy, ms); qqq_r = window_ret(qqq, ms)
        f_all = [ann[p][c] for c in cur]
        f_rank = [ann[p][c] for c in ciks]
        rho = spearman([score[c] for c in ciks], f_rank)
        # 1年の持続（過去1年 vs 翌年）: 前の年にもいた全員
        q1 = p - 100
        both1 = [c for c in cur if q1 in ann and c in ann[q1]]
        rho1 = spearman([ann[q1][c] for c in both1], [ann[p][c] for c in both1]) if both1 else None
        # 十分位ごとの翌年の平均
        dec = []
        for d_ in range(10):
            a_, z_ = round(n * d_ / 10), round(n * (d_ + 1) / 10)
            grp = ciks[a_:z_]
            dec.append(round(S.mean(ann[p][c] for c in grp) * 100, 2) if grp else None)
        top_m = basket_monthly([cur[c]['O'] for c in top]); bot_m = basket_monthly([cur[c]['O'] for c in bot])
        all_m = basket_monthly([cur[c]['O'] for c in cur])
        top_m30 = basket_monthly([cur[c]['P30'] for c in top]); bot_m30 = basket_monthly([cur[c]['P30'] for c in bot])
        for d_, src in ((top_series, top_m), (bot_series, bot_m), (all_series, all_m), (top_series_p30, top_m30), (bot_series_p30, bot_m30)):
            d_.update(src)
        tw = agg_weights([cur[c]['w_ok'] for c in top])
        to = turnover(tw, prev_top_w) if prev_top_w is not None else None
        if to is not None:
            turns.append(to)
        prev_top_w = tw
        # 感度: 過去1年の上位10% ／ 過去3年の上位5% ／ 上位20%
        s1 = {c: ann[q1][c] for c in cur if q1 in ann and c in ann[q1]}
        c1 = sorted(s1, key=lambda c: -s1[c]); k1 = max(1, math.ceil(len(c1) * TOP_FRAC))
        sens['past1_top10'][p] = S.mean(ann[p][c] for c in c1[:k1]) if c1 else None
        sens['past1_bot10'][p] = S.mean(ann[p][c] for c in c1[-k1:]) if c1 else None
        k5 = max(1, math.ceil(n * 0.05)); k20 = max(1, math.ceil(n * 0.20))
        sens['past3_top5'][p] = S.mean(ann[p][c] for c in ciks[:k5])
        sens['past3_top20'][p] = S.mean(ann[p][c] for c in ciks[:k20])
        # 集中型（銘柄 10〜40）の中だけで上位10%
        conc = [c for c in ciks if cur[c]['n'] <= 40]
        kc = max(1, math.ceil(len(conc) * TOP_FRAC))
        sens['conc_top10'][p] = S.mean(ann[p][c] for c in conc[:kc]) if conc else None
        sens['conc_bot10'][p] = S.mean(ann[p][c] for c in conc[-kc:]) if conc else None
        top_list = sorted(tw.items(), key=lambda x: -x[1])[:25]
        rows.append({'period': p, 'hold_from': ms[0], 'hold_to': ms[-1], 'full_year': full_years[p],
                     'n_with_3y': n, 'n_kept_this_year': len(cur), 'n_top': k,
                     'top_mean': round(S.mean(ann[p][c] for c in top) * 100, 2),
                     'top_mean_P30': round(comp([top_m30[m] for m in sorted(top_m30)]) * 100, 2),
                     'bot_mean': round(S.mean(ann[p][c] for c in bot) * 100, 2),
                     'bot_mean_P30': round(comp([bot_m30[m] for m in sorted(bot_m30)]) * 100, 2),
                     'ranked_mean': round(S.mean(f_rank) * 100, 2), 'all_kept_mean': round(S.mean(f_all) * 100, 2),
                     'all_kept_median': round(S.median(f_all) * 100, 2),
                     'spy': round(spy_r * 100, 2) if spy_r is not None else None,
                     'qqq': round(qqq_r * 100, 2) if qqq_r is not None else None,
                     'top_minus_spy': round((S.mean(ann[p][c] for c in top) - spy_r) * 100, 2) if spy_r is not None else None,
                     'bot_minus_spy': round((S.mean(ann[p][c] for c in bot) - spy_r) * 100, 2) if spy_r is not None else None,
                     'spearman_past3_next': round(rho, 3) if rho is not None else None,
                     'spearman_past1_next': round(rho1, 3) if rho1 is not None else None, 'n_past1_pairs': len(both1),
                     'decile_next_mean_pct': dec,
                     'top_past3_median_pct': round(S.median(score[c] for c in top) * 100, 1),
                     'top_median_value_usd_m': round(S.median(cur[c]['value_usd'] for c in top) / 1e6, 1),
                     'all_median_value_usd_m': round(S.median(cur[c]['value_usd'] for c in cur) / 1e6, 1),
                     'top_median_n_stocks': S.median(cur[c]['n'] for c in top),
                     'top_turnover_oneway_vs_prev': round(to, 3) if to is not None else None,
                     'top_basket_top25': [[secinfo[p][cu][0], secinfo[p][cu][1], round(x * 100, 2)] for cu, x in top_list],
                     'top_managers': [[cur[c]['name'], round(score[c] * 100, 1), round(ann[p][c] * 100, 1)] for c in top[:15]]})
        print(p, 'n', n, 'top', rows[-1]['top_mean'], 'bot', rows[-1]['bot_mean'], 'spy', rows[-1]['spy'], 'rho', rows[-1]['spearman_past3_next'], flush=True)
    return yearly, counts, rows, {'top': top_series, 'bot': bot_series, 'all': all_series, 'top_P30': top_series_p30,
                                  'bot_P30': bot_series_p30}, sens, turns, spy, qqq


def summarize(rows, series, sens, turns, spy, qqq):
    full = [r for r in rows if r['full_year']]
    part = [r for r in rows if not r['full_year']]
    months_full = []
    for r in full:
        months_full += [m for m in hold_months(r['period'])]
    win = lambda d: {m: d[m] for m in months_full if m in d}
    out = {}
    mean_to = S.mean(turns) if turns else None
    cost_ann = 2 * mean_to * COST_ONEWAY if mean_to is not None else None   # 売り T と買い T の両方に片道 0.2%
    for nm in ('top', 'bot', 'all', 'top_P30', 'bot_P30'):
        s_ = win(series[nm])
        st = M.excess_stats(s_, spy)
        stq = M.excess_stats(s_, qqq)
        e = {'vs_spy_monthly': st, 'vs_qqq_monthly': stq, 'max_dd': round(M.maxdd(s_) * 100, 1),
             'cagr': round(M.cagr(s_) * 100, 2)}
        if nm.startswith('top'):
            sn = M.apply_cost(s_, 1.0, cost_ann) if cost_ann is not None else None
            e['vs_spy_after_cost'] = M.excess_stats(sn, spy) if sn else None
        out[nm] = e
    out['spy_cagr_same_window'] = round(M.cagr(win(spy)) * 100, 2)
    out['spy_max_dd_same_window'] = round(M.maxdd(win(spy)) * 100, 1)
    out['qqq_cagr_same_window'] = round(M.cagr(win(qqq)) * 100, 2)
    # 年次の点（翌年の成績の単純平均 − SPY）
    def yearly_stats(key):
        xs = [r[key] for r in full if r.get(key) is not None]
        return {'n_years': len(xs), 'mean_pct': round(S.mean(xs), 2) if xs else None,
                'median_pct': round(S.median(xs), 2) if xs else None,
                'years_positive': sum(1 for x in xs if x > 0),
                't_simple': round(t_simple(xs), 2) if t_simple(xs) is not None else None,
                't_nw_lag1': round(nw_t_small(xs), 2) if nw_t_small(xs) is not None else None, 'values': xs}
    out['annual_top_minus_spy'] = yearly_stats('top_minus_spy')
    out['annual_bot_minus_spy'] = yearly_stats('bot_minus_spy')
    tb = [r['top_mean'] - r['bot_mean'] for r in full]
    out['annual_top_minus_bot'] = {'mean_pct': round(S.mean(tb), 2), 'years_positive': sum(1 for x in tb if x > 0), 'n_years': len(tb),
                                   't_simple': round(t_simple(tb), 2) if t_simple(tb) else None, 'values': [round(x, 2) for x in tb]}
    ra = [r['top_mean'] - r['ranked_mean'] for r in full]
    out['annual_top_minus_ranked_avg'] = {'mean_pct': round(S.mean(ra), 2), 'years_positive': sum(1 for x in ra if x > 0),
                                          't_simple': round(t_simple(ra), 2) if t_simple(ra) else None}
    am = [r['all_kept_mean'] - r['spy'] for r in full]
    out['annual_all_managers_minus_spy'] = {'mean_pct': round(S.mean(am), 2), 'years_positive': sum(1 for x in am if x > 0),
                                            't_simple': round(t_simple(am), 2) if t_simple(am) else None}
    rho = [r['spearman_past3_next'] for r in full if r['spearman_past3_next'] is not None]
    rho1 = [r['spearman_past1_next'] for r in full if r['spearman_past1_next'] is not None]
    out['spearman_past3_next'] = {'mean': round(S.mean(rho), 3), 'median': round(S.median(rho), 3),
                                  'years_positive': sum(1 for x in rho if x > 0), 'n_years': len(rho),
                                  't_across_years': round(t_simple(rho), 2) if t_simple(rho) else None, 'values': rho}
    out['spearman_past1_next'] = {'mean': round(S.mean(rho1), 3), 'median': round(S.median(rho1), 3),
                                  'years_positive': sum(1 for x in rho1 if x > 0), 'n_years': len(rho1),
                                  't_across_years': round(t_simple(rho1), 2) if t_simple(rho1) else None, 'values': rho1}
    # 十分位の平均（年をならす）
    dec = [S.mean(r['decile_next_mean_pct'][d] for r in full) for d in range(10)]
    out['decile_next_mean_pct_avg'] = [round(x, 2) for x in dec]
    out['decile_note'] = '0＝過去3年の成績が最上位の1/10・9＝最下位の1/10。各年の翌年の成績（O）の平均を年でならした'
    # 前半・後半
    def half(a, z):
        rr = [r for r in full if a <= r['period'] <= z]
        ms_ = []
        for r in rr:
            ms_ += hold_months(r['period'])
        s_ = {m: series['top'][m] for m in ms_ if m in series['top']}
        b_ = {m: series['bot'][m] for m in ms_ if m in series['bot']}
        st = M.excess_stats(s_, spy) if len(s_) >= 24 else None
        sb = M.excess_stats(b_, spy) if len(b_) >= 24 else None
        return {'formation_years': [r['period'] // 100 for r in rr], 'hold_from': rr[0]['hold_from'] if rr else None,
                'hold_to': rr[-1]['hold_to'] if rr else None,
                'top_minus_spy_annual_mean_pct': round(S.mean(r['top_minus_spy'] for r in rr), 2) if rr else None,
                'top_vs_spy_monthly': st, 'bot_vs_spy_monthly': sb,
                'spearman_mean': round(S.mean(r['spearman_past3_next'] for r in rr), 3) if rr else None}
    out['half1'] = half(201612, 201912)
    out['half2'] = half(202012, 202412)
    out['mean_turnover_oneway'] = round(mean_to, 3) if mean_to is not None else None
    out['cost_per_year_pct'] = round(cost_ann * 100, 3) if cost_ann is not None else None
    # 感度
    sv = {}
    for k, d in sens.items():
        xs = [(d[r['period']] - r['spy'] / 100) * 100 for r in full if d.get(r['period']) is not None]
        sv[k] = {'mean_minus_spy_pct': round(S.mean(xs), 2) if xs else None, 'years_positive': sum(1 for x in xs if x > 0),
                 'n_years': len(xs), 't_simple': round(t_simple(xs), 2) if t_simple(xs) else None}
    out['sensitivity_annual_minus_spy'] = sv
    # 合格の線（R2 の E3 と同じ線を参考に当てる）
    st = out['top'].get('vs_spy_after_cost') or {}
    h1 = out['half1']['top_vs_spy_monthly'] or {}; h2 = out['half2']['top_vs_spy_monthly'] or {}
    crit = {'after_cost_ex_ge_1pct': (st.get('ex_ann') or -99) >= 1.0, 'nw_t_ge_2': (st.get('t') or -99) >= 2.0,
            'half1_positive': (h1.get('ex_ann') or -99) > 0, 'half2_positive': (h2.get('ex_ann') or -99) > 0}
    out['pass_bar_E3_line'] = {'criteria': crit, 'pass': all(crit.values()),
                               'note': 'R2 の pass_bar（費用後 SPY に +1%/年以上・NW t≥2・前半と後半の両方で正）をそのまま上位10%のかごに当てた'}
    out['partial_year'] = [{'period': r['period'], 'months': f"{r['hold_from']}〜{r['hold_to']}",
                            'top_minus_spy_pct': r['top_minus_spy'], 'top_mean': r['top_mean'], 'spy': r['spy']} for r in part]
    return out


if __name__ == '__main__':
    os.makedirs(C, exist_ok=True)
    a = sys.argv[1:]
    if '--fetch' in a:
        fetch()
    elif '--parse' in a:
        parse()
    elif '--calc' in a:
        main()
    elif '--map' in a:
        do_map()
    elif '--parse1' in a:
        parse_one(int(a[a.index('--parse1') + 1]))
