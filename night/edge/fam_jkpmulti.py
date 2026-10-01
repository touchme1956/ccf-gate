#!/usr/bin/env python3
"""night/edge/fam_jkpmulti.py — 系統 jkpmulti: JKP 米国の三分位（153の特徴）の『良い側』を合成して買いだけで持つ

事前登録 out/edge_prereg.json の round1_families.jkpmulti。相手は French の米国市場（上限なしの時価加重）。
  ・良い側 = 予言の向き（JKP all_factors の direction）どおりの端の三分位（+1 → '3.0'、−1 → '1.0'）
    （JKP の因子 = direction ×（'3.0' − '1.0'）であることを米国で確かめた: 相関 ±1.000）
  ・JKP の三分位の 'ret' は米ドルの**超過リターン**（米国の短期金利を引いたもの）→ 総リターン = ret + French RF
  ・JKP の 'mkt' も超過リターン（vw は French の Mkt-RF と平均差 0.006%/月）→ 国の相手 = 'mkt'(vw) + RF
  ・費用: 片道の回転100%につき 0.25%。回転は特徴の種類で置く（下の turn_ann）。合成の中の重みの戻しと入れ替えも数える

使い方: python3 night/fam_jkpmulti.py … ではなく  python3 night/edge/fam_jkpmulti.py  → 変種を振って spec を凍結（選定の段だけ）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h
import csv, io, json, math, re, statistics as S, zipfile
from concurrent.futures import ThreadPoolExecutor

FAMILY = {
    'key': 'jkpmulti',
    'name': '米国株の「良い側」の合成（JKP 三分位・買いだけ）',
    'implement': ('実行は二通り。(1) 自分で選ぶ: 楽天証券の米国株（NISA 成長投資枠で可）で、合成に入れた特徴ごとに米国の大型〜中型株を'
                  'スクリーニングし、良い側の三分位の銘柄を時価加重（上限あり）で毎月〜毎年入れ替える＝数百銘柄になり個人には重い。'
                  '(2) 近似: 同じ向きの米国の因子ETF（例: 割安 VLUE・IUSV、質 QUAL、勢い MTUM、低ぶれ USMV、多因子 LRGF・GSLC）を'
                  '合成の比で持つ。ETF は楽天証券で買え、NISA 成長投資枠の対象のものが多い（レバレッジ型ではない）。'
                  '⚠ ETF は JKP の三分位そのものではない（銘柄数・重み・入れ替えの規則が違う）ので、成績は近似でしかない'),
}

JKP = 'https://jkpfactors-data.s3.amazonaws.com/public/'
COST = 0.0025                     # 片道の回転100%につき（事前登録: 個別株の組）
START = 196307                    # Compustat の時代（文献の標準の始まり）
MIN_N = 50                        # 良い側の三分位の銘柄数がこれ未満の月は使わない（分散の足りない組を避ける）
MIN_N_REPL = 20                   # 他の国（小さい市場が多い）
REPL = ['jpn', 'gbr', 'deu', 'fra', 'can', 'aus', 'che', 'swe', 'nld', 'ita', 'esp', 'hkg', 'sgp', 'dnk', 'nor', 'bel',
        'fin', 'aut', 'irl', 'prt', 'nzl', 'isr']

# 回転（年率・片道）。事前登録の既定は 価格 200%/年・会計 50%/年。**分かっている速い信号は既定より重く置く**（費用を軽く見せないため）
ONE_MONTH = {'ret_1_0', 'seas_1_1an', 'seas_1_1na'}
QUARTERLY_FAST = {'niq_su', 'saleq_su', 'ni_inc8q', 'niq_at_chg1', 'niq_be_chg1', 'saleq_gr1', 'mispricing_perf'}
PRICE = {'ami_126d', 'beta_60m', 'beta_dimson_21d', 'betabab_1260d', 'betadown_252d', 'bidaskhl_21d', 'corr_1260d', 'coskew_21d',
         'dolvol_126d', 'dolvol_var_126d', 'iskew_capm_21d', 'iskew_ff3_21d', 'iskew_hxz4_21d', 'ivol_capm_21d', 'ivol_capm_252d',
         'ivol_ff3_21d', 'ivol_hxz4_21d', 'market_equity', 'prc', 'prc_highprc_252d', 'resff3_12_1', 'resff3_6_1', 'ret_12_1',
         'ret_12_7', 'ret_1_0', 'ret_3_1', 'ret_60_12', 'ret_6_1', 'ret_9_1', 'rmax1_21d', 'rmax5_21d', 'rmax5_rvol_21d', 'rskew_21d',
         'rvol_21d', 'turnover_126d', 'turnover_var_126d', 'zero_trades_126d', 'zero_trades_21d', 'zero_trades_252d',
         'seas_11_15an', 'seas_11_15na', 'seas_16_20an', 'seas_16_20na', 'seas_1_1an', 'seas_1_1na', 'seas_2_5an', 'seas_2_5na',
         'seas_6_10an', 'seas_6_10na'}


def turn_ann(ch):
    if ch in ONE_MONTH:
        return 10.0
    if ch.endswith('_21d') or ch == 'ret_3_1':
        return 4.0
    if ch in PRICE or ch in QUARTERLY_FAST:
        return 2.0
    return 0.5


# ───────────────────────── 読み込み ─────────────────────────
_MEMO = {}


def meta():
    if 'meta' not in _MEMO:
        _MEMO['meta'] = _meta()
    return _MEMO['meta']


def _meta():
    """→ (direction, cluster, 公表年)。direction は JKP all_factors の列、cluster は JKP の13テーマ、公表年は Factor Details の引用"""
    url = f'{JKP}%5Busa%5D_%5Ball_factors%5D_%5Bmonthly%5D_%5Bvw_cap%5D.zip'
    z = zipfile.ZipFile(io.BytesIO(h.cached('jkp_factor_usa_all_factors_vw_cap.zip', url)))
    d = {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        d.setdefault(x['name'], int(x['direction']))
    gh = 'https://raw.githubusercontent.com/bkelly-lab/ReplicationCrisis/master/GlobalFactors/'
    cl = {x['characteristic']: x['cluster'] for x in
          csv.DictReader(io.StringIO(h.cached('jkp_meta_Cluster_Labels.csv', gh + 'Cluster%20Labels.csv', 365).decode()))}
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(h.cached('jkp_meta_Factor_Details.xlsx', gh + 'Factor%20Details.xlsx', 365)), read_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    yr = {}
    for r in rows[1:]:
        q = dict(zip(rows[0], r))
        if q['abr_jkp']:
            y = re.findall(r'(19\d\d|20\d\d)', str(q['cite']))
            yr[q['abr_jkp']] = int(y[0]) if y else None
    return d, cl, yr


def _counts(region, ch, w):
    """三分位の銘柄数 n（h.jkp は返さないので、同じキャッシュを h.cached で読み h.guard を通す）"""
    url = f'{JKP}portfolios/%5B{region}%5D_%5B{ch}%5D_%5Bmonthly%5D_%5B{w}%5D.zip'
    z = zipfile.ZipFile(io.BytesIO(h.cached(f'jkp_portfolio_{region}_{ch}_{w}.zip', url)))
    out = {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        try:
            out.setdefault(x['pf'], {})[int(x['date'][:4]) * 100 + int(x['date'][5:7])] = int(float(x['n']))
        except (TypeError, ValueError):
            continue
    return {k: h.guard(v) for k, v in out.items()}


def leg(region, ch, side, w):
    """良い側の脚 → (超過リターン {m}, 銘柄数 {m})。取れなければ ({}, {})"""
    try:
        p = h.jkp(region, ch, 'portfolio', w)
        n = _counts(region, ch, w)
    except Exception:
        return {}, {}
    return p.get(side, {}), n.get(side, {})


def legs(region, chars_sides, w):
    need = [cs for cs in chars_sides if (region, cs[0], cs[1], w) not in _MEMO]
    if need:
        with ThreadPoolExecutor(8) as ex:
            for cs, v in zip(need, ex.map(lambda cs: leg(region, cs[0], cs[1], w), need)):
                _MEMO[(region, cs[0], cs[1], w)] = v
    return {c: _MEMO[(region, c, sd, w)] for c, sd in chars_sides}


# ───────────────────────── 合成 ─────────────────────────
def composite(L, rf, months, min_n, weights_fn, tfun=turn_ann):
    """L: {特徴: (超過リターン, 銘柄数)}。weights_fn(m, active) → {特徴: 目標の重み}（合計1）。
    月 m の持ち高は m−1 月末に決まる: active は『月 m の組が m−1 月末に組まれた時点の銘柄数』で決まる（n は組んだ時点の数）。
    → ret {m: 総リターン}・tv {m: 片道の回転}（脚の中の入れ替え＋重みの戻し・入れ替え）"""
    ret, tv, prev = {}, {}, None
    for m in months:
        if m not in rf:
            continue
        act = [c for c, (r, n) in L.items() if m in r and n.get(m, 0) >= min_n]
        tw = weights_fn(m, act) if act else {}
        tw = {c: x for c, x in tw.items() if x > 0}
        if not tw:
            continue
        within = sum(x * tfun(c) / 12 for c, x in tw.items())
        reb = 0.0 if prev is None else 0.5 * sum(abs(prev.get(c, 0.0) - tw.get(c, 0.0)) for c in set(prev) | set(tw))
        r = sum(x * L[c][0][m] for c, x in tw.items()) + rf[m]
        ret[m], tv[m] = r, within + reb
        g = {c: x * (1 + L[c][0][m] + rf[m]) for c, x in tw.items()}
        s = sum(g.values())
        prev = {c: v / s for c, v in g.items()} if s > 0 else None
    return ret, tv


def equal_w(sel):
    sel = list(sel)

    def f(m, act):
        a = [c for c in sel if c in act]
        return {c: 1 / len(a) for c in a} if a else {}
    return f


def theme_w(themes, cl):
    """選んだテーマを等分し、テーマの中は取れる特徴を等分"""
    def f(m, act):
        th = {}
        for c in act:
            if cl.get(c) in themes:
                th.setdefault(cl[c], []).append(c)
        if not th:
            return {}
        return {c: 1 / len(th) / len(cs) for t, cs in th.items() for c in cs}
    return f


def ex_t(ret, mk, rf, tv, a, b):
    """費用後の月次超過の t（a〜b・共通の月）"""
    x = [ret[m] - tv.get(m, 0.0) * COST - mk[m] for m in sorted(ret) if a <= m <= b and m in mk]
    if len(x) < 60:
        return None, len(x)
    sd = S.stdev(x)
    return (S.mean(x) / (sd / math.sqrt(len(x))) if sd > 0 else None), len(x)


def walk_w(L, pool, mk, rf, topn, first_pick, rank_start, min_n, by_theme=None):
    """前進選択: 毎年12月 R に、rank_start〜R の費用後の超過の t で上位 topn を選び、R+1〜R+12 に持つ（R までの情報だけ）。
    by_theme=cl なら特徴ではなくテーマ（テーマの中は等分）を選ぶ"""
    single = {}
    if by_theme is None:
        for c in pool:
            single[c] = composite({c: L[c]}, rf, sorted(L[c][0]), min_n, equal_w([c]))
    else:
        for t in sorted({by_theme[c] for c in pool}):
            cs = [c for c in pool if by_theme[c] == t]
            single[t] = composite({c: L[c] for c in cs}, rf, sorted({m for c in cs for m in L[c][0]}), min_n, equal_w(cs))
    picks = {}

    def pick(R):
        if R not in picks:
            sc = []
            for k, (r, tv) in single.items():
                t, n = ex_t(r, mk, rf, tv, rank_start, R)
                if t is not None:
                    sc.append((t, k))
            sc.sort(reverse=True)
            picks[R] = [k for _, k in sc[:topn]]
        return picks[R]

    def f(m, act):
        y, mo = divmod(m, 100)
        R = (y - 1) * 100 + 12                 # 直前の12月（月 m の持ち高は R 月末までの情報で決まる）
        if R < first_pick:
            return {}
        sel = pick(R)
        if by_theme is None:
            a = [c for c in sel if c in act]
            return {c: 1 / len(a) for c in a} if a else {}
        th = {}
        for c in act:
            if by_theme.get(c) in sel:
                th.setdefault(by_theme[c], []).append(c)
        return {c: 1 / len(th) / len(cs) for t, cs in th.items() for c in cs} if th else {}
    return f, picks


def build(spec, region='usa', mk=None, rf=None, min_n=None):
    """spec どおりに一つの地域で合成 → (ret, tv, 追加情報)"""
    w = spec['w']
    D, CL, YR = meta()
    min_n = spec.get('min_n', MIN_N) if min_n is None else min_n
    mode = spec['mode']
    if mode in ('static', 'theme_static'):
        cs = spec['chars']
    else:
        cs = spec['pool']
    fs = spec.get('sides') or {}                 # 凍結した側（無ければ JKP の direction から）
    side = {c: fs.get(c) or ('3.0' if D[c] > 0 else '1.0') for c in cs}
    L = legs(region, [(c, side[c]) for c in cs], w)
    L = {c: v for c, v in L.items() if v[0]}
    months = sorted({m for v in L.values() for m in v[0]})
    months = [m for m in months if m >= spec.get('start', START)]
    info = {}
    if mode == 'static':
        fn = equal_w(cs)
    elif mode == 'theme_static':
        fn = theme_w(set(spec['themes']), CL)
    elif mode in ('walk', 'theme_walk'):
        rs = spec.get('rank_start', START) if region == 'usa' else min(months or [START])
        fp = spec['first_pick'] if region == 'usa' else h.add_months(rs, 12 * spec.get('walk_years', 10) - 1) // 100 * 100 + 12
        fn, picks = walk_w(L, list(L), mk, rf, spec['topn'], fp, rs, min_n, CL if mode == 'theme_walk' else None)
        info['picks'] = picks
    else:
        raise ValueError(mode)
    ta = spec.get('turn_ann') or {}
    ret, tv = composite(L, rf, months, min_n, fn, lambda c: ta.get(c, turn_ann(c)))
    return ret, tv, info


def run(spec):
    mk, rf = h.us_market()
    ret, tv, _ = build(spec, 'usa', mk, rf)
    out = {'ret': ret, 'bench': mk, 'rf': rf, 'turnover': tv, 'cost': COST, 'markets': {}}
    for c in spec.get('replicate', []):
        try:
            jm = h.jkp(c, 'mkt', 'factor', 'vw')          # その国の市場（上限なしの時価加重・米ドルの超過）
        except Exception:
            continue
        bench = {m: v + rf[m] for m, v in jm.items() if m in rf}
        r, t, _ = build(spec, c, bench, rf, min_n=spec.get('min_n_repl', MIN_N_REPL))
        if len(r) >= 24:
            out['markets'][c] = {'ret': r, 'bench': bench, 'rf': rf, 'turnover': t, 'cost': COST}
    return out


# ───────────────────────── 選定（2000-12 まで） ─────────────────────────
def census(mk, rf):
    """153の特徴それぞれの良い側を1本ずつ（vw_cap と vw）→ {(w, 特徴): 選定期間の成績}。これが『見た特徴の数』"""
    D, CL, YR = meta()
    out = {}
    for w in ('vw_cap', 'vw'):
        for c in sorted(D):
            r, tv, _ = build({'mode': 'static', 'chars': [c], 'w': w}, 'usa', mk, rf)
            out[(w, c)] = h.stats(r, mk, rf, a=START, b=h.SEL_END, turnover=tv, cost=COST)
    return out


def variants(single):
    """収益を見る前に決めた変種の一覧（scratchpad の計画どおり）。→ [(名前, spec, 選べるか)]
    選べるのはプール K（原論文の公表年 ≤2000）だけ。プール A（153 全部）は参考: 2001年以降に公表された特徴は、
    発見者がホールドアウトの期間のデータを見て見つけたものなので、2000年末の規則に入れると後知恵が混ざる"""
    D, CL, YR = meta()
    allc = sorted(D)
    known = [c for c in allc if YR.get(c) and YR[c] <= 2000]
    tt = lambda w, c: (single[(w, c)] or {}).get('t') if single.get((w, c)) else None

    def top(pool, w, n):
        return sorted(pool, key=lambda c: -(tt(w, c) if tt(w, c) is not None else -99))[:n]
    V = []
    for n in (1, 3, 5, 10, 20):
        V.append((f'K・vw_cap・上位{n}', {'mode': 'static', 'w': 'vw_cap', 'chars': top(known, 'vw_cap', n)}, True))
    V.append(('K・vw_cap・全部を等分', {'mode': 'static', 'w': 'vw_cap', 'chars': known}, True))
    th_k = sorted({CL[c] for c in known})
    V.append(('K・vw_cap・テーマ均等', {'mode': 'theme_static', 'w': 'vw_cap', 'chars': known, 'themes': th_k}, True))
    return V, known, th_k


def theme_rank(known, w, mk, rf):
    D, CL, YR = meta()
    out = []
    for t in sorted({CL[c] for c in known}):
        cs = [c for c in known if CL[c] == t]
        r, tv, _ = build({'mode': 'static', 'chars': cs, 'w': w}, 'usa', mk, rf)
        st = h.stats(r, mk, rf, a=START, b=h.SEL_END, turnover=tv, cost=COST)
        out.append((st['t'] if st else -99, t, cs, st))
    out.sort(key=lambda x: -x[0])
    return out


def all_variants(single, mk, rf):
    D, CL, YR = meta()
    allc = sorted(D)
    V, known, th_k = variants(single)
    tt = lambda w, c: (single.get((w, c)) or {}).get('t')

    def top(pool, w, n):
        return sorted(pool, key=lambda c: -(tt(w, c) if tt(w, c) is not None else -99))[:n]
    tr = theme_rank(known, 'vw_cap', mk, rf)
    V.append(('K・vw_cap・最良のテーマ1つ', {'mode': 'theme_static', 'w': 'vw_cap', 'chars': tr[0][2], 'themes': [tr[0][1]]}, True))
    t3 = tr[:3]
    V.append(('K・vw_cap・上位3テーマ', {'mode': 'theme_static', 'w': 'vw_cap', 'chars': [c for x in t3 for c in x[2]],
                                       'themes': [x[1] for x in t3]}, True))
    best_each = [top([c for c in known if CL[c] == t], 'vw_cap', 1)[0] for t in th_k]
    V.append(('K・vw_cap・各テーマの最良1つ', {'mode': 'static', 'w': 'vw_cap', 'chars': best_each}, True))
    V.append(('K・vw_cap・t≥2の全部', {'mode': 'static', 'w': 'vw_cap', 'chars': [c for c in known if (tt('vw_cap', c) or -9) >= 2]}, True))
    for n in (5, 10):
        V.append((f'K・vw_cap・前進選択 上位{n}', {'mode': 'walk', 'w': 'vw_cap', 'pool': known, 'topn': n, 'first_pick': 197212,
                                                   'rank_start': START}, True))
    V.append(('K・vw_cap・前進選択 上位3テーマ', {'mode': 'theme_walk', 'w': 'vw_cap', 'pool': known, 'topn': 3, 'first_pick': 197212,
                                              'rank_start': START}, True))
    for n in (5, 10):
        V.append((f'K・vw・上位{n}', {'mode': 'static', 'w': 'vw', 'chars': top(known, 'vw', n)}, True))
    V.append(('K・vw・全部を等分', {'mode': 'static', 'w': 'vw', 'chars': known}, True))
    for n in (1, 3, 5, 10, 20):
        V.append((f'A・vw_cap・上位{n}（参考）', {'mode': 'static', 'w': 'vw_cap', 'chars': top(allc, 'vw_cap', n)}, False))
    V.append(('A・vw_cap・全部を等分（参考）', {'mode': 'static', 'w': 'vw_cap', 'chars': allc}, False))
    V.append(('A・vw_cap・テーマ均等（参考）', {'mode': 'theme_static', 'w': 'vw_cap', 'chars': allc, 'themes': sorted(set(CL.values()))}, False))
    V.append(('A・vw_cap・前進選択 上位10（参考）', {'mode': 'walk', 'w': 'vw_cap', 'pool': allc, 'topn': 10, 'first_pick': 197212,
                                                 'rank_start': START}, False))
    return V, known


def select(save=False):
    assert h.PHASE == 'select'
    mk, rf = h.us_market()
    capm = {m: v + rf[m] for m, v in h.jkp('usa', 'mkt', 'factor', 'vw_cap').items() if m in rf}
    single = census(mk, rf)
    V, known = all_variants(single, mk, rf)
    rows = []
    for name, sp, ok in V:
        r, tv, info = build(sp, 'usa', mk, rf)
        st = h.stats(r, mk, rf, b=h.SEL_END, turnover=tv, cost=COST)
        st2 = h.stats(r, capm, rf, b=h.SEL_END, turnover=tv, cost=COST)
        avg_tv = sum(tv.values()) / len(tv) * 12 if tv else None
        rows.append({'name': name, 'eligible': ok, 'spec': sp, 'stats': st, 'ex_vs_capped_mkt': st2['excess'] if st2 else None,
                     'turnover_yr': round(avg_tv, 2) if avg_tv else None, 'n_chars': len(sp.get('chars') or sp.get('pool') or []),
                     'picks_last': info.get('picks', {}).get(max(info.get('picks', {}) or [0]), None) if info.get('picks') else None})
        print(f"{'○' if ok else '参'} {name:34} n{rows[-1]['n_chars']:3} {st['from']}〜 ex{st['excess']:6} t{st['t']:6} (NW{st['t_nw']}) "
              f"vol{st['vol']}/{st['bench_vol']} dd{st['maxdd']}/{st['bench_maxdd']} 回転{rows[-1]['turnover_yr']} 対capmkt {rows[-1]['ex_vs_capped_mkt']}  10年窓{st['roll10_win']}")
    return single, rows, known


LOOKAHEAD = ('scratchpad の lookahead.py で3通り確かめた（すべて食い違い0）: '
             '(1) EDGE_SEL_END=199012 と 200012 で別プロセスに走らせ、1990-12 までの規則・相手・他の市場（jpn/gbr/can/aus）の月次が 1e-12 で一致（規則 330か月・相手 774か月）。'
             '(2) 未来の毒: 1985-12 より後の脚のリターン・銘柄数・短期金利・市場をすべて乱数に置き換えても、1985-12 以前の規則のリターンと回転が1か月も変わらない'
             '（静的な上位10・前進選択の上位5の両方。前進選択は毎年12月までの情報で翌年の組を決める）。'
             '(3) 脚の最後の1か月を削っても、それ以前の449か月が変わらない。'
             '月 m の組は JKP が m−1 月末に組んだ三分位（会計は4か月以上遅らせてある）で、使う銘柄数 n も組んだ時点の数。合成の重みは等分（全期間の平均や標準化を使わない）')


def main():
    single, rows, known = select()
    elig = [r for r in rows if r['eligible'] and r['stats'] and r['stats']['excess'] >= 1.0]
    best = max(elig, key=lambda r: r['stats']['t'])
    D, CL, YR = meta()
    spec = dict(best['spec'])
    spec.update({'start': START, 'min_n': MIN_N, 'min_n_repl': MIN_N_REPL, 'replicate': REPL,
                 'sides': {c: ('3.0' if D[c] > 0 else '1.0') for c in spec.get('chars') or spec.get('pool')},
                 'turn_ann': {c: turn_ann(c) for c in spec.get('chars') or spec.get('pool')},
                 'themes_of_chars': {c: CL[c] for c in spec.get('chars') or spec.get('pool')},
                 'published': {c: YR[c] for c in spec.get('chars') or spec.get('pool')}})
    r = run(spec)
    st = h.stats(r['ret'], r['bench'], r['rf'], b=h.SEL_END, turnover=r['turnover'], cost=r['cost'])
    mkt_sel = {}
    for c, x in r['markets'].items():
        s2 = h.stats(x['ret'], x['bench'], x['rf'], b=h.SEL_END, turnover=x['turnover'], cost=x['cost'])
        if s2:
            mkt_sel[c] = {'from': s2['from'], 'years': s2['years'], 'excess': s2['excess'], 't': s2['t']}
    tbl = [{'name': x['name'], 'eligible': x['eligible'], 'n_chars': x['n_chars'], 'from': x['stats']['from'],
            'excess': x['stats']['excess'], 't': x['stats']['t'], 't_nw': x['stats']['t_nw'], 'vol': x['stats']['vol'],
            'maxdd': x['stats']['maxdd'], 'turnover_yr': x['turnover_yr'], 'ex_vs_jkp_capped_mkt': x['ex_vs_capped_mkt'],
            'chars': x['spec'].get('chars') if x['spec']['mode'] == 'static' else None,
            'themes': x['spec'].get('themes')} for x in rows]
    top_single = sorted(((v['t'], c) for (w, c), v in single.items() if w == 'vw_cap' and v), reverse=True)
    rationale = (
        '【規則】2000年末までに論文で公表されていた米国株の特徴（JKP の153のうち37）の中から、1963-07〜2000-12 の'
        '「良い側の三分位（vw_cap）− French 米国市場 − 費用」の t が高い10本を選び、その10の買いだけの組を等分に持つ（毎月戻す）。'
        f'選ばれた10本: {", ".join(spec["chars"])}＝割安4（fcf_me 簿価外のキャッシュフロー利回り・ni_me 益回り・ival_me 本源的価値/時価・be_me 簿価/時価）、'
        '勢い2（ret_12_1・ret_9_1）、利益の勢い2（niq_su 決算サプライズ・dsale_dinv 売上の伸び−在庫の伸び）、発生主義の利益が小さい1（oaccruals_at）、'
        'Piotroski の F スコア1（f_score）。'
        '【なぜ】(1) 経済的な理由が別々: 割安はリスクの対価または過剰な悲観（Basu 1983・Fama-French 1992・Lakonishok-Shleifer-Vishny 1994）、'
        '勢い・決算サプライズは情報への反応の遅れ（Jegadeesh-Titman 1993・Foster-Olsen-Shevlin 1984・Bernard-Thomas 1989）、'
        '発生主義は利益の質の見誤り（Sloan 1996）、F スコアは割安の中の財務の健全さ（Piotroski 2000）、在庫は売上の質（Abarbanell-Bushee 1998）。'
        '割安と勢いは負に相関するので合わせると市場との差のぶれが小さくなる（Asness 1997）。'
        '(2) 公表が2000年以前の特徴だけに限った: 2001年以降に公表された特徴（質 QMJ・粗利/総資産 等）は、発見者が2001年以降のデータを見て'
        '見つけたものなので、2000年末の規則に入れるとホールドアウトに後知恵が混ざる（これは収益を見る前に決めた）。'
        '(3) 買いだけ: 個人は空売りできない。良い側の三分位だけを持ち、売りの側の上乗せは取らない。'
        f'【選定期間 {st["from"]}〜{st["to"]}（{st["years"]}年）】費用後の年率 {st["cagr"]}% 対 市場 {st["bench_cagr"]}%、超過 +{st["excess"]}%/年、'
        f't {st["t"]}（Newey-West {st["t_nw"]}）、ぶれ {st["vol"]}% 対 {st["bench_vol"]}%、最大下落 {st["maxdd"]}% 対 {st["bench_maxdd"]}%、'
        f'転がる10年で市場に勝った窓 {st["roll10_win"]}。回転は年 {best["turnover_yr"]} 回（費用 年{round(best["turnover_yr"] * COST * 100, 2)}%）。'
        f'JKP の上限つき市場（vw_cap）に対しては +{best["ex_vs_capped_mkt"]}%/年＝上限つきの重み（小型寄り）の分が約 {round(st["excess"] - best["ex_vs_capped_mkt"], 2)}%/年 含まれる。'
        '【選び方】事前登録どおり、選べる17変種（公表≤2000 のプール）の中で「費用後の超過の t」が最大かつ超過 +1%/年以上のもの。'
        '次点は 上位10 と t の差 0.1 以内に 上位5（vw 5.47・vw_cap 5.42）・上位10（vw 5.42）が並ぶ＝この差は偶然の幅の中。'
        '【予想】McLean-Pontiff（2016）は公表後に上乗せが約半分に縮むと報告している。選定期間の +4%/年 は半分以下に縮むと見るのが相場。'
    )
    extra = {'implement': FAMILY['implement'], 'lookahead_test': LOOKAHEAD, 'variants_table': tbl, 'markets': list(r['markets']),
             'markets_selection_period': mkt_sel,
             'features_seen': {'count': len(D), 'note': '153の特徴すべての良い側を vw_cap と vw の両方で1本ずつ測った（306本の系列）。変種（合成）の数 n_variants とは別に数える。'
                               '選べる変種は公表≤2000 の37本からだけ作った', 'top10_single_vw_cap_all153': [[round(t, 2), c] for t, c in top_single[:10]]},
             'pool_known_by_2000': known, 'eligible_variants': sum(1 for x in rows if x['eligible']),
             'reference_variants': sum(1 for x in rows if not x['eligible']),
             'benchmark': 'French 米国市場（Mkt-RF＋RF・CRSP 全上場の上限なし時価加重）。他の国は JKP の国の mkt（vw＝上限なし・米ドル超過）＋French RF',
             'cost_note': ('片道の回転100%につき0.25%。回転は 年次の会計の信号 50%/年・価格と四半期の変化の信号 200%/年・21日の信号と ret_3_1 400%/年・'
                           '1か月の信号 1000%/年（事前登録の既定より速い信号は重く置いた）＋合成の中の重みの戻し')}
    doc = h.save_spec('jkpmulti', spec, rationale, len(rows), st, extra)
    print('凍結:', best['name'], st)
    return doc


if __name__ == '__main__':
    main() if '--save' in sys.argv else select()
