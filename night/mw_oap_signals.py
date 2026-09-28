#!/usr/bin/env python3
"""night/mw_oap_signals.py — 市場に勝てる歴史検証（角度 oap_signals: JKP に無い情報源の予言因子の『良い側の端』）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて」。読むだけ（門・採点・配分には不使用）。
事前登録: out/mw_oap_signals_prereg.json（この道具の最初の版と一緒に、測る前にコミット）。線は out/mw_prereg.json。

問い: Open Source Asset Pricing（Chen & Zimmermann・2025-10 版・〜2024-12）の予言因子ごとに、原論文の符号で決まる
      良い側の端（時価加重の第10十分位・参考に第5五分位）だけを買って持つと、純粋な時価加重の米国市場（French Mkt）に
      訓練期間（〜2006）と保有期間（2007〜2024）の両方で勝ったか。主の族は JKP に無い情報源
      （アナリスト予想〔IBES〕・オプション〔OptionMetrics〕・13F・出来事・空売り残高）。

データ: OAP の Google Drive 公開フォルダ（openassetpricing パッケージの urls.py と同じ release 2025.10）から
        PredictorAltPorts_DecilesVW / QuintilesVW / LiqScreen_VWforce と SignalDoc.csv。French の Mkt-RF と RF。
        JKP の all_factors 三分位（'vw'）と地域の vw 市場（重なりの確かめと C5）。

使い方: python3 night/mw_oap_signals.py --check   … データと単位だけ確かめる（戦略と市場の比較は計算しない）
        python3 night/mw_oap_signals.py           … 全部計算して out/mw_oap_signals.json へ
"""
import sys, os, re, io, csv, json, math, zipfile, collections, subprocess, argparse, pickle, statistics as S

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402

_ORIG_S = M.S


class _FastStats:
    """mw_postpub.py と同じ置き換え（mw_common は共有なので書き換えない）。
    mw_common.excess_stats は β の式で S.mean を要素ごとに呼び直す（O(n²)）うえ、標準の statistics は分数の厳密計算で遅い。
    mw_common が参照する統計関数（mean/pvariance/stdev）だけを math.fsum の同じ式に差し替える。
    元の関数と同じ値を返すことは check_fast_stats() が毎回確かめる"""
    _last = None

    @staticmethod
    def mean(x):
        c = _FastStats._last
        if c is not None and c[0] is x:
            return c[1]
        xs = x if isinstance(x, (list, tuple)) else list(x)
        v = math.fsum(xs) / len(xs)
        if isinstance(x, (list, tuple)):
            _FastStats._last = (x, v)
        return v

    @staticmethod
    def pvariance(x):
        m = math.fsum(x) / len(x)
        return math.fsum((v - m) ** 2 for v in x) / len(x)

    @staticmethod
    def stdev(x):
        m = math.fsum(x) / len(x)
        return math.sqrt(math.fsum((v - m) ** 2 for v in x) / (len(x) - 1))


PREREG = 'mw_oap_signals_prereg.json'
OUT = 'mw_oap_signals.json'
COST = 0.003          # 片道売買100%あたり 0.30%（判定）
COST_LO = 0.001       # 参考（大型株）
NMIN = 20             # 良い側の銘柄数がこれ未満の月は欠測
COMP_MIN = 3          # 束ねる戦略は3本以上そろう月だけ
DATA_END = 202412     # OAP の終わり
REGIONS_C5 = ('developed', 'emerging')
REGIONS_INFO = ('jpn',)
REG_START = 199001
DRIVE = 'https://drive.usercontent.google.com/download?id={}&export=download&confirm=t'
FILES = {  # release 2025.10（Google Drive フォルダ 1qQDuTsnyvWfEJR6nPBQZ8xxlq6bkLG_y を一覧して得た ID）
    'DecilesVW': ('1_1WWZqilrt1gleeyAFwjv5aobd0QRbS3', 'oap202510_PredictorAltPorts_DecilesVW.zip'),
    'QuintilesVW': ('1ef905SSlCDyh1KU9W1tJs5sfBFz0HPUt', 'oap202510_PredictorAltPorts_QuintilesVW.zip'),
    'VWforce': ('1KZE3FgBxFPaNOyxoRw63ubZHOlkR9kZW', 'oap202510_PredictorAltPorts_LiqScreen_VWforce.zip'),
}
SIGNALDOC = ('1rdi0jTPSA6xtn6TpQAMT5WyEczQ1gK59', 'oap_SignalDoc.csv')
DETAILS = os.path.join(M.CACHE, 'jkp_factor_details.xlsx')
DETAILS_URL = 'https://raw.githubusercontent.com/bkelly-lab/ReplicationCrisis/master/GlobalFactors/Factor%20Details.xlsx'

PRIM_CAT = ('Analyst', 'Options', '13F', 'Event')
PRIM_EXTRA = ('ShortInterest', 'PredictedFE')
FAST = ['STreversal', 'MaxRet', 'ReturnSkew', 'ReturnSkew3F', 'IdioVol3F', 'RealizedVol', 'betaVIX', 'IndRetBig',
        'MomSeason', 'MomSeason06YrPlus', 'MomSeason11YrPlus', 'MomSeason16YrPlus', 'MomSeasonShort', 'AnnouncementReturn',
        'dVolCall', 'dVolPut', 'dCPVolSpread', 'AnalystRevision', 'ChangeInRecommendation', 'OptionVolume2', 'UpRecomm', 'DownRecomm']
PER = {'1.0': 2.0, '3.0': 1.0, '6.0': 0.7, '12.0': 0.5, '36.0': 0.3, '': 0.5}


def turnover(doc_row):
    return 6.0 if doc_row['Acronym'] in FAST else PER.get(doc_row['Portfolio Period'], 0.5)


# ───────────────────────── 取得・読み込み ─────────────────────────
def signaldoc():
    M.get(DRIVE.format(SIGNALDOC[0]), name=SIGNALDOC[1], max_age_days=3650)
    rows = list(csv.DictReader(open(os.path.join(M.CACHE, SIGNALDOC[1]), encoding='utf-8')))
    return {r['Acronym']: r for r in rows if r['Cat.Signal'] == 'Predictor'}


def load_ports(key):
    """{signal: {port: {ym: (ret小数, Nlong or None)}}} と signallag の平均 {signal: {port: 平均}}。
    ret が空・NA の行は入れない（欠測を0と読まない）。解析結果は out/_mw_cache に pickle で置く"""
    fid, fname = FILES[key]
    pk = os.path.join(M.CACHE, fname + '.parsed.pkl')
    src = os.path.join(M.CACHE, fname)
    if os.path.exists(pk) and os.path.exists(src) and os.path.getmtime(pk) >= os.path.getmtime(src):
        return pickle.load(open(pk, 'rb'))
    b = M.get(DRIVE.format(fid), name=fname, max_age_days=3650)
    z = zipfile.ZipFile(io.BytesIO(b))
    f = io.TextIOWrapper(z.open(z.namelist()[0]), encoding='utf-8')
    P = collections.defaultdict(lambda: collections.defaultdict(dict))
    lag = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in csv.DictReader(f):
        if r['ret'] in ('', 'NA'):
            continue
        ym = int(r['date'][:4]) * 100 + int(r['date'][5:7])
        n = r.get('Nlong')
        n = int(float(n)) if n not in (None, '', 'NA') else None
        P[r['signalname']][r['port']][ym] = (float(r['ret']) / 100, n)
        sl = r.get('signallag')
        if sl not in (None, '', 'NA') and r['port'] != 'LS':
            v = float(sl)
            if math.isfinite(v):
                lag[r['signalname']][r['port']].append(v)
    P = {s: {p: dict(v) for p, v in d.items()} for s, d in P.items()}
    L = {s: {p: math.fsum(v) / len(v) for p, v in d.items() if v} for s, d in lag.items()}
    tmp = pk + f'.{os.getpid()}.tmp'
    pickle.dump((P, L), open(tmp, 'wb'))
    os.replace(tmp, pk)
    return P, L


def leg(P, s, port, dropped=None):
    """良い側のポートフォリオ → {ym: ret}。Nlong<NMIN の月は外す（0で埋めない）。OAP の終わり以降は外す"""
    out = {}
    for ym, (r, n) in P[s][port].items():
        if ym > DATA_END:
            continue
        if n is not None and n < NMIN:
            if dropped is not None:
                dropped[s] = dropped.get(s, 0) + 1
            continue
        out[ym] = r
    return out


def max_port(P, s):
    return max(p for p in P[s] if p != 'LS')


# ───────────────────────── JKP ─────────────────────────
def jkp_details():
    import openpyxl
    if not os.path.exists(DETAILS):
        M.get(DETAILS_URL, name='jkp_factor_details.xlsx', max_age_days=3650)
    wb = openpyxl.load_workbook(DETAILS, read_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    h = rows[0]
    D = {}
    for r in rows[1:]:
        d = dict(zip(h, r))
        a = d.get('abr_jkp')
        if not a:
            continue
        m = re.search(r'\((\d{4})\)', str(d.get('cite') or ''))
        first = re.split(r'[ ,]', str(d.get('cite') or '').strip())[0].lower()
        D[a] = {'direction': int(d['direction']), 'cite': d.get('cite'),
                'key': (first.replace('assness', 'asness').replace('jegedeesh', 'jegadeesh'), int(m.group(1))) if m else None}
    return D


def jkp_good(region, JD):
    """{特徴: {ym: 良い側の三分位の超過}}（'vw'・n<NMIN の月は外す）"""
    P = collections.defaultdict(dict)
    for r in M.jkp_rows(region, 'all_factors', 'portfolios', 'vw'):
        a = r['name']
        if a not in JD or r['ret'] in ('', 'NA', 'na'):
            continue
        if r['pf'] != ('3.0' if JD[a]['direction'] == 1 else '1.0'):
            continue
        if r['n'] not in ('', 'NA', 'na') and float(r['n']) < NMIN:
            continue
        ym = M._ym(r['date'])
        P[a][ym] = float(r['ret'])
    return dict(P)


def active(s, b):
    return {k: s[k] - b[k] for k in s if k in b}


def corr_on(a, b, lo=None, hi=None, nmin=36):
    ks = sorted(k for k in set(a) & set(b) if (lo is None or k >= lo) and (hi is None or k <= hi))
    if len(ks) < nmin:
        return None
    return round(M.corr([a[k] for k in ks], [b[k] for k in ks]), 3)


# ───────────────────────── 評価 ─────────────────────────
def evaluate(s, b, turn, pub=None):
    ks = sorted(set(s) & set(b))
    s = {k: s[k] for k in ks}; b = {k: b[k] for k in ks}
    e = {'start': ks[0] if ks else None, 'end': ks[-1] if ks else None, 'months': len(ks),
         'full': M.excess_stats(s, b), 'train': M.excess_stats(s, b, z=M.TRAIN_END),
         'hold': M.excess_stats(s, b, a=M.HOLD_START), 'recent': M.excess_stats(s, b, a=M.RECENT_START),
         'turnover_per_year': turn}
    e['post_pub'] = ({'from': (pub + 1) * 100 + 1, 'stats': M.excess_stats(s, b, a=(pub + 1) * 100 + 1)} if pub else None)
    e['cost_hold'] = M.excess_stats(M.apply_cost(s, turn, COST), b, a=M.HOLD_START)
    e['cost_hold_10bp'] = M.excess_stats(M.apply_cost(s, turn, COST_LO), b, a=M.HOLD_START)
    e['cost_full'] = M.excess_stats(M.apply_cost(s, turn, COST), b)
    e['roll20'] = M.rolling(s, b, 20)
    e['roll10'] = M.rolling(s, b, 10)
    e['dca20'] = M.dca(s, b, 20)
    hs = M.window(s, M.HOLD_START); hb = M.window(b, M.HOLD_START)
    e['maxdd_hold'] = [round(M.maxdd(hs) * 100, 1), round(M.maxdd(hb) * 100, 1)] if hs else None
    tr = e['train']
    e['train_short_flag'] = bool(tr and tr['years'] < 15)
    return e


def git_sha(path):
    try:
        return subprocess.check_output(['git', 'log', '-n1', '--format=%H', '--', path], cwd=M.BASE).decode().strip() or None
    except Exception:  # noqa
        return None


def check_fast_stats():
    """置き換えた統計関数が元の statistics と同じ値を返すか（小さな合成データで）"""
    import random
    rnd = random.Random(7)
    s = {199001 + (i // 12) * 100 + i % 12: rnd.gauss(0.01, 0.05) for i in range(96)}
    b = {k: v * 0.8 + rnd.gauss(0.002, 0.02) for k, v in s.items()}
    M.S = _ORIG_S
    a = M.excess_stats(s, b)
    M.S = _FastStats
    f = M.excess_stats(s, b)
    return a == f, a, f


# ───────────────────────── 検査だけ ─────────────────────────
def sanity(ff, doc, Pd, Ld, Pq, Pv, Lv):
    san = {}
    mkt = ff['mkt']
    san['french_mkt_cagr_full'] = round(M.cagr(mkt) * 100, 2)
    san['french_mkt_cagr_2007'] = round(M.cagr(M.window(mkt, M.HOLD_START)) * 100, 2)
    san['french_mkt_cagr_2007_2024'] = round(M.cagr(M.window(mkt, M.HOLD_START, DATA_END)) * 100, 2)
    san['french_mkt_cagr_192607_202412'] = round(M.cagr(M.window(mkt, None, DATA_END)) * 100, 2)
    # 単位: Size の第1十分位（符号つき＝−log(時価) が最も小さい＝最大の会社）と French Mkt / Mkt-RF（1927〜2006）
    sz = {k: v[0] for k, v in Pd['Size']['01'].items()}
    ks = sorted(k for k in set(sz) & set(mkt) if 192701 <= k <= 200612)
    d_tot = S.mean([sz[k] - mkt[k] for k in ks]) * 1200
    d_ex = S.mean([sz[k] - ff['mktrf'][k] for k in ks]) * 1200
    c = M.corr([sz[k] for k in ks], [mkt[k] for k in ks])
    san['units_size_decile01'] = {'months': len(ks), 'mean_diff_vs_Mkt_total_pct': round(d_tot, 2),
                                  'mean_diff_vs_MktRF_pct': round(d_ex, 2), 'corr_vs_Mkt': round(c, 4),
                                  'signallag_01_vs_10': [round(Ld['Size']['01'], 2), round(Ld['Size']['10'], 2)],
                                  'verdict': ('総リターン（%）で確定' if abs(d_tot) < 1.5 and c > 0.95 and d_ex > d_tot + 1.0 else '要確認')}
    # LS＝最大番号−01・signallag の単調性
    for name, P, L in (('DecilesVW', Pd, Ld), ('VWforce', Pv, Lv)):
        bad, mono, n = 0, 0, 0
        for s in P:
            ps = sorted(p for p in P[s] if p != 'LS'); lo, hi = ps[0], ps[-1]
            ms = [m for m in P[s]['LS'] if m in P[s][lo] and m in P[s][hi]]
            dif = S.mean([abs(P[s]['LS'][m][0] - (P[s][hi][m][0] - P[s][lo][m][0])) for m in ms]) if ms else 1
            bad += dif > 1e-6
            if s in L and lo in L[s] and hi in L[s]:
                n += 1
                mono += L[s][hi] > L[s][lo]
        san[f'ls_equals_top_minus_bottom_{name}'] = {'signals': len(P), 'violations': bad}
        san[f'signallag_top_gt_bottom_{name}'] = {'signals_with_lag': n, 'top_gt_bottom': mono}
    san['signals_in_signaldoc_predictors'] = len(doc)
    san['signals_DecilesVW'] = len(Pd); san['signals_QuintilesVW'] = len(Pq); san['signals_VWforce'] = len(Pv)
    ok, a, f = check_fast_stats()
    san['fast_stats_equal_to_statistics'] = ok
    return san


def check():
    doc = signaldoc()
    Pd, Ld = load_ports('DecilesVW'); Pq, _ = load_ports('QuintilesVW'); Pv, Lv = load_ports('VWforce')
    ff = M.ff_factors()
    print(json.dumps(sanity(ff, doc, Pd, Ld, Pq, Pv, Lv), ensure_ascii=False, indent=1))
    prim = [a for a, r in doc.items() if r['Cat.Data'] in PRIM_CAT or a in PRIM_EXTRA]
    print('主の族', len(prim), '連続', sum(1 for a in prim if a in Pd))


# ───────────────────────── 本体 ─────────────────────────
def main():
    doc = signaldoc()
    Pd, Ld = load_ports('DecilesVW')
    Pq, _ = load_ports('QuintilesVW')
    Pv, Lv = load_ports('VWforce')
    ff = M.ff_factors()
    MKT = ff['mkt']
    out = {'angle': 'oap_signals', 'prereg': PREREG, 'prereg_commit': git_sha(os.path.join('out', PREREG)),
           'benchmark': 'French Mkt（Mkt-RF + RF・総リターン）。OAP の ret（CRSP の総リターン・%）を小数にして総リターンどうしで比べる',
           'data': 'Open Source Asset Pricing Data Release 2025.10（〜2024-12）: PredictorAltPorts_DecilesVW / QuintilesVW / LiqScreen_VWforce・SignalDoc.csv',
           'cost_per_100pct_oneway_grading': COST, 'cost_reference': COST_LO, 'n_min_stocks': NMIN, 'data_end': DATA_END}
    san = sanity(ff, doc, Pd, Ld, Pq, Pv, Lv)
    out['sanity'] = san
    if san['units_size_decile01']['verdict'] != '総リターン（%）で確定' or not san['fast_stats_equal_to_statistics']:
        print('健全性の検査に失敗', json.dumps(san, ensure_ascii=False)[:2000])
        sys.exit(1)
    out['deviations'] = [
        'mw_common.excess_stats の β の式が S.mean を要素ごとに呼び直す O(n²)・標準 statistics の分数計算で遅いため、mw_postpub と同じく mw_common が参照する統計関数（mean/pvariance/stdev）だけを math.fsum の同じ式へ差し替えて実行（mw_common は書き換えていない・合成データで excess_stats の全項目一致を毎回確認: sanity.fast_stats_equal_to_statistics）']

    # ── 良い側の端 ──
    dropped = {}
    legs, legq, meta = {}, {}, {}
    for a, r in doc.items():
        cont = a in Pd
        port = '10' if cont else max_port(Pv, a)
        legs[a] = leg(Pd if cont else Pv, a, port, dropped)
        if a in Pq:
            legq[a] = leg(Pq, a, '05')
        meta[a] = {'cat_data': r['Cat.Data'], 'form': r['Cat.Form'], 'pub': int(r['Year']) if r['Year'].isdigit() else None,
                   'turn': turnover(r), 'desc': r['LongDescription'], 'authors': r['Authors'],
                   'file_port': f"DecilesVW:10" if cont else f"VWforce:{port}",
                   'primary': r['Cat.Data'] in PRIM_CAT or a in PRIM_EXTRA}
    out['months_dropped_nlong_lt20_long_leg'] = {k: v for k, v in sorted(dropped.items(), key=lambda x: -x[1])}

    # ── JKP の重なり・C5 の相手 ──
    JD = jkp_details()
    jg = jkp_good('usa', JD)
    jm = M.jkp_mkt('usa', 'vw')
    jact = {a: active(v, jm) for a, v in jg.items()}
    RG = {reg: jkp_good(reg, JD) for reg in REGIONS_C5 + REGIONS_INFO}
    RM = {reg: M.jkp_mkt(reg, 'vw') for reg in REGIONS_C5 + REGIONS_INFO}

    def overlap(a, s):
        act = active(s, MKT)
        tr = {j: corr_on(act, v, hi=M.TRAIN_END) for j, v in jact.items()}
        tr = {j: c for j, c in tr.items() if c is not None}
        near = max(tr, key=lambda j: tr[j]) if tr else None
        key = None
        au = re.split(r'[ ,]', (meta[a]['authors'] or '').strip())[0].lower()
        if meta[a]['pub']:
            key = (au, meta[a]['pub'])
        cites = [j for j, d in JD.items() if d['key'] == key and j in tr]
        cite_best = max(cites, key=lambda j: tr[j]) if cites else None
        cp, why = None, None
        if cite_best and tr[cite_best] >= 0.5:
            cp, why = cite_best, '著者・年が一致・訓練の相関≥0.5'
        elif near and tr[near] >= 0.7:
            cp, why = near, '著者・年の一致なし（または<0.5）・153特徴で最も近く訓練の相関≥0.7'
        o = {'nearest_jkp': near, 'nearest_train_corr': tr.get(near) if near else None,
             'nearest_full_corr': corr_on(act, jact[near]) if near else None,
             'cite_candidates': cites, 'cite_best': cite_best, 'cite_best_train_corr': tr.get(cite_best) if cite_best else None,
             'c5_counterpart': cp, 'c5_counterpart_why': why}
        o['duplicate_of_jkp'] = bool(o['nearest_full_corr'] is not None and o['nearest_full_corr'] >= 0.8)
        return o

    def repl(cp):
        if not cp:
            return None, None
        det, pos = {}, 0
        for reg in REGIONS_C5 + REGIONS_INFO:
            g = RG[reg].get(cp)
            if not g:
                det[reg] = None
                continue
            st_full = M.excess_stats(g, RM[reg], a=REG_START)
            st_hold = M.excess_stats(g, RM[reg], a=M.HOLD_START)
            okp = bool(st_full and st_full['ex_ann'] > 0)
            det[reg] = {'full': st_full, 'hold': st_hold, 'positive': okp, 'counted': reg in REGIONS_C5}
            if reg in REGIONS_C5 and okp:
                pos += 1
        return {'regions': len(REGIONS_C5), 'positive': pos}, det

    # ── 特徴ごと（P / PQ / S / SQ） ──
    rows = []
    for fam, use_q in (('P', False), ('PQ', True), ('S', False), ('SQ', True)):
        for a in sorted(doc):
            m = meta[a]
            if m['primary'] != (fam in ('P', 'PQ')):
                continue
            if use_q and a not in legq:
                continue
            s = legq[a] if use_q else legs[a]
            if not s:
                rows.append({'id': f'{fam}:{a}', 'family': fam, 'signal': a, 'grade': 'C', 'note': '良い側の銘柄数が全月20未満＝評価できない'})
                continue
            e = evaluate(s, MKT, m['turn'], m['pub'])
            ov = overlap(a, s)
            rp, rdet = repl(ov['c5_counterpart'])
            nl = [n for (ym, (r, n)) in (Pq[a]['05'] if use_q else (Pd[a]['10'] if a in Pd else Pv[a][max_port(Pv, a)])).items()
                  if ym >= M.HOLD_START and n is not None]
            rows.append({'id': f'{fam}:{a}', 'family': fam, 'primary': fam == 'P', 'signal': a, 'cat_data': m['cat_data'],
                         'form': m['form'], 'pub_year': m['pub'], 'desc': m['desc'],
                         'portfolio': ('QuintilesVW:05' if use_q else m['file_port']),
                         'nlong_hold_median': (sorted(nl)[len(nl) // 2] if nl else None),
                         'eval': e, 'jkp_overlap': ov, 'repl': rp, 'repl_detail': rdet})

    # ── 束ねる戦略（PC） ──
    def comp(members, src, rt=False):
        months = sorted(set().union(*[set(src[a]) for a in members if a in src])) if members else []
        ret, cnt, trn = {}, {}, {}
        for ym in months:
            act = [a for a in members if a in src and ym in src[a] and (not rt or (meta[a]['pub'] and ym >= (meta[a]['pub'] + 1) * 100 + 1))]
            if len(act) < COMP_MIN:
                continue
            ret[ym] = math.fsum(src[a][ym] for a in act) / len(act)
            cnt[ym] = len(act)
            trn[ym] = math.fsum(meta[a]['turn'] for a in act) / len(act)
        return ret, cnt, trn

    prim = [a for a in doc if meta[a]['primary']]
    allp = list(doc)
    specs = [
        ('PC_new_dec', '主の族の良い側の端すべて', prim, legs, False),
        ('PC_new_dec_rt', '主の族・公表の翌年1月から（実時間の採用者）', prim, legs, True),
        ('PC_new_q', '主の族の連続の予言因子の第5五分位', [a for a in prim if a in legq], legq, False),
        ('PC_all_dec', '全212予言因子の良い側の端', allp, legs, False),
        ('PC_all_dec_rt', '全212予言因子・公表の翌年1月から（実時間の採用者）', allp, legs, True),
        ('PC_analyst', 'Cat.Data=Analyst', [a for a in doc if meta[a]['cat_data'] == 'Analyst'], legs, False),
        ('PC_options', 'Cat.Data=Options', [a for a in doc if meta[a]['cat_data'] == 'Options'], legs, False),
        ('PC_13F_si', 'Cat.Data=13F＋ShortInterest', [a for a in doc if meta[a]['cat_data'] == '13F' or a == 'ShortInterest'], legs, False),
        ('PC_event', 'Cat.Data=Event', [a for a in doc if meta[a]['cat_data'] == 'Event'], legs, False),
    ]
    for name, desc, mem, src, rt in specs:
        r, cnt, trn = comp(mem, src, rt)
        th = S.mean([t for k, t in trn.items() if k >= M.HOLD_START]) if any(k >= M.HOLD_START for k in trn) else S.mean(trn.values())
        e = evaluate(r, MKT, round(th, 3), None)
        ks = sorted(r)
        rows.append({'id': name, 'family': 'PC', 'primary': False, 'description': desc, 'n_members': len(mem),
                     'legs_first': cnt[ks[0]] if ks else None, 'legs_2006': cnt.get(200612), 'legs_2024': cnt.get(202412),
                     'eval': e, 'repl': None, 'note_c5': '束ねた戦略の米国外の同じ規則は無い＝C5 は N/A'})

    # ── Holm と格付け ──
    fams = collections.defaultdict(dict)
    for x in rows:
        if 'eval' in x:
            fams[x['family']][x['id']] = (x['eval']['hold'] or {}).get('p')
    hp = {f: M.holm(d) for f, d in fams.items()}
    for x in rows:
        if 'eval' not in x:
            x['holm_p_hold'] = None
            x['criteria'] = None
            continue
        e = x['eval']
        x['holm_p_hold'] = hp[x['family']].get(x['id'])
        g, c = M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['cost_hold'],
                       repl=x['repl'], family_holm_p=x['holm_p_hold'])
        x['grade'], x['criteria'] = g, c
    out['family_sizes'] = {f: {'n': sum(1 for x in rows if x['family'] == f),
                               'n_evaluable_hold': sum(1 for v in d.values() if v is not None)} for f, d in fams.items()}

    # ── 要約 ──
    def hx(x, k='hold'):
        return ((x.get('eval') or {}).get(k) or {}).get('ex_ann')
    summ = {}
    for f in ('P', 'PQ', 'S', 'SQ', 'PC'):
        fr = [x for x in rows if x['family'] == f and 'eval' in x]
        hs = [x for x in fr if x['eval']['hold']]
        summ[f] = {'n': len([x for x in rows if x['family'] == f]),
                   'grades': dict(collections.Counter(x['grade'] for x in rows if x['family'] == f)),
                   'hold_positive': sum(1 for x in hs if x['eval']['hold']['ex_ann'] > 0),
                   'hold_positive_net': sum(1 for x in hs if x['eval']['cost_hold'] and x['eval']['cost_hold']['ex_ann'] > 0 and x['eval']['cost_hold']['cagr_diff'] > 0),
                   'hold_t_ge_1.65': sum(1 for x in hs if (x['eval']['hold']['t'] or 0) >= 1.65),
                   'train_pass_C1': sum(1 for x in fr if x['criteria'] and x['criteria']['C1_train']),
                   'mean_hold_ex': round(S.mean([x['eval']['hold']['ex_ann'] for x in hs]), 2) if hs else None,
                   'mean_train_ex': round(S.mean([x['eval']['train']['ex_ann'] for x in fr if x['eval']['train']]), 2) if fr else None,
                   'top_hold': [(x['id'], x['grade'], hx(x), x['eval']['hold']['t']) for x in sorted(hs, key=lambda x: -x['eval']['hold']['ex_ann'])[:8]]}
    out['summary_by_family'] = summ
    # 公表後の減衰（報告のみ）: 特徴ごとの 訓練 vs 公表後 vs 保有
    pp = [x for x in rows if x['family'] in ('P', 'S') and 'eval' in x and x['eval']['post_pub'] and x['eval']['post_pub']['stats'] and x['eval']['train']]
    out['post_pub_decay'] = {
        'n': len(pp),
        'mean_train_ex': round(S.mean([x['eval']['train']['ex_ann'] for x in pp]), 2) if pp else None,
        'mean_postpub_ex': round(S.mean([x['eval']['post_pub']['stats']['ex_ann'] for x in pp]), 2) if pp else None,
        'postpub_positive': sum(1 for x in pp if x['eval']['post_pub']['stats']['ex_ann'] > 0),
        'primary_only': {
            'n': sum(1 for x in pp if x['family'] == 'P'),
            'mean_train_ex': round(S.mean([x['eval']['train']['ex_ann'] for x in pp if x['family'] == 'P']), 2) if any(x['family'] == 'P' for x in pp) else None,
            'mean_postpub_ex': round(S.mean([x['eval']['post_pub']['stats']['ex_ann'] for x in pp if x['family'] == 'P']), 2) if any(x['family'] == 'P' for x in pp) else None}}
    dup = [x['id'] for x in rows if (x.get('jkp_overlap') or {}).get('duplicate_of_jkp')]
    out['jkp_duplicates'] = {'n': len(dup), 'ids': dup}
    out['tested'] = rows
    out['n_tested'] = len(rows)
    p = M.save(OUT, out)
    print('書いた', p, os.path.getsize(p))
    for f in ('P', 'PQ', 'PC', 'S', 'SQ'):
        print(f, json.dumps(summ[f], ensure_ascii=False))
    for x in rows:
        if x.get('grade') in ('S', 'A', 'B'):
            e = x['eval']
            print(x['id'], x['grade'], 'train', (e['train'] or {}).get('ex_ann'), (e['train'] or {}).get('t'),
                  'hold', (e['hold'] or {}).get('ex_ann'), (e['hold'] or {}).get('t'), (e['hold'] or {}).get('cagr_diff'),
                  'net', (e['cost_hold'] or {}).get('ex_ann'), 'roll20', (e['roll20'] or {}).get('win_rate'),
                  'holm', x['holm_p_hold'], 'repl', x['repl'])


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()
    M.S = _FastStats
    if args.check:
        check()
    else:
        main()
