#!/usr/bin/env python3
"""night/morefunds.py — メガ10のほかの候補と SCHD（2026-10-11・ユーザー「もっとないの？ メガ10はいいと思うけどその他にも」「SCHD面白いのでは？」）

読むだけ。門・採点・配分には触れない。事前登録 out/morefunds_prereg.json（5d5b4d6・測る前に固定）どおり。

第1部 SCHD を『その他 ETF・投資信託 15%』に
  ITA を選んだときと同じ物差し（night/etf_forward_rank → etf_forward_combo → etf_p15 の4つの世界・席A・etf_ita_xlk の判定の決まりと感度5本）に
  候補 SCHD_R（楽天・シュワブ・高配当株式・米国ファンド〔資産成長型〕＝SCHD を持つ投信）を足す。足し方は etf_forward_rank の口
  （EXTRA_PROXY・EXTRA_STYLE・EXTRA_PROFILES）と etf_forward_combo.CANDS への追加だけ＝他の21本の数字は変わらない（自己検問で確かめる）。
    データ   SCHD の月次（Yahoo・2011-11〜）＋ 2011-10 以前は代理（VEIPX か French の D/P 上位30%・重なる期間の相関が高いほう）
    費用     楽天・シュワブの実質の信託報酬 0.1238%（税込・SCHD の経費込み）＋ 米国の源泉10%×配当利回り（NISA で戻らない）
    B・C     型の上乗せは VYM と同じ D/P 上位30%（SCHD の最初のふるいは配当）／ C は JPM の DIV
  J1 SCHD を入れる価値（SCHD_R の形 − NASDAQ100 の形）／ J2 ITA を SCHD に替えるか（SCHD_R の形 − ITA の形）
  SCHD だけの感度（表に出す・まとめの本数に数えない）: P1 代理をもう一方に／P2 B の型を D/P 上位30% と BIG HiOP の平均に／P3 費用を実測に

第2部 メガ10の仲間（判定はしない・実在の記録の参考の測定）
  W1 2017-10〜（FANG+ の公表後）・W2 2008-01〜・W3 2000-11〜 の年率・ぶれ・最大下落（円とドル）、投信の基準価額、形の例、集中の度合い、基礎率

出力: out/morefunds.json
"""
import datetime, json, math, os, sys, time, unicodedata, re
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etf_forward_rank as R      # noqa: E402
import etf_forward_combo as CB    # noqa: E402
import etf_p15 as P               # noqa: E402
import etf_ita_xlk as IX          # noqa: E402
import mw_common as M             # noqa: E402
import gaps_common as G           # noqa: E402

OUT = os.path.join(BASE, 'out', 'morefunds.json')
PROF = os.path.join(BASE, 'out', 'morefunds_profiles.json')
PREREG = 'out/morefunds_prereg.json（5d5b4d6）'
CACHE = os.path.join(BASE, 'out', '_nx_cache', 'morefunds')
JITA = os.path.join(BASE, 'out', '_nx_cache', 'newfunds', 'jita_full.json')   # newfunds と同じ写真（2026-10-09）

SCHD_ER = 0.0006
VEIPX_ER = 0.0027          # VEIPX の今の経費率（事前登録: 代理の期間に (0.27%−0.06%)/12 を毎月足し戻す）
VEH_ER = 0.001238          # 楽天・シュワブ（資産成長型）の実質の信託報酬（税込・投信ライブラリー trustReward×1.1）
SCHD_ISIN_Q, SCHD_ASSOC_Q = 'JP90C000R6N1', '9I312249'   # 楽天・シュワブ（四半期決算型・2024-09-18）＝P3 の実測
W_OVL = (201111, 202609)   # SCHD の記録（代理を選ぶ相関の窓・実績の表の窓）
SEAT_BASE, SLOT = {'QQQM': 50, 'SMH': 20}, 15
CASTLE = IX.CASTLE


# ───────────────────────── 第1部 ─────────────────────────
def months(a, b):
    return R.months(a, b)


def proxy_veipx():
    r = M.yahoo('VEIPX')
    return {k: v + (VEIPX_ER - SCHD_ER) / 12 for k, v in r.items()}


def proxy_french():
    s = M.french_series('Portfolios_Formed_on_D-P', want='Value Weight Returns')['Hi 30']
    return {k: v - SCHD_ER / 12 for k, v in s.items()}


PROXIES = {'VEIPX_ADJ': ('VEIPX（Vanguard Equity Income・費用の差を足し戻す）', proxy_veipx),
           'FRENCH_DP_HI30': ('French の配当利回り上位30%（時価総額加重・SCHD の経費を引く）', proxy_french)}


def pick_proxy():
    schd = M.yahoo('SCHD')
    ks = [k for k in months(*W_OVL) if k in schd]
    out = {}
    for name, (ja, fn) in PROXIES.items():
        p = fn()
        kk = [k for k in ks if k in p]
        out[name] = dict(ja=ja, months=len(kk), corr=round(M.corr([schd[k] for k in kk], [p[k] for k in kk]), 4),
                         geo_schd=round(100 * R.geo(schd, kk), 2), geo_proxy=round(100 * R.geo(p, kk), 2), first=kk[0], last=kk[-1])
    a, b = out['VEIPX_ADJ']['corr'], out['FRENCH_DP_HI30']['corr']
    main = 'VEIPX_ADJ' if a >= b else 'FRENCH_DP_HI30'          # 同点なら VEIPX（事前登録）
    return main, out


def load_profiles():
    return json.load(open(PROF, encoding='utf-8'))


def register(proxy, prof):
    R.C['SCHD_R'] = dict(ja='米国高配当（SCHD）', veh='楽天・シュワブ・高配当株式・米国ファンド（資産成長型）＝SCHD を持つ投信', us=True, k=0.10)
    R.DATA['SCHD_R'] = ('SCHD', proxy, 201110)
    R.JPM_MAP['SCHD_R'] = 'DIV'
    R.GMO_MAP['SCHD_R'] = [('USL', .5), ('USDV', .5)]   # VYM と同じ
    R.EXTRA_PROXY.update({k: v[1] for k, v in PROXIES.items()})
    R.EXTRA_STYLE['SCHD_R'] = 'VYM'
    s = prof['SCHD']
    hold = [[h[0], h[1]] for h in s['holdings'] if h[0] and h[0] != 'n/a']
    R.EXTRA_PROFILES['SCHD'] = dict(er=SCHD_ER, dy=s['dy'], holdings=hold)          # データの器（SCHD そのもの）
    R.EXTRA_PROFILES['SCHD_R'] = dict(er=VEH_ER, dy=s['dy'], holdings=hold)         # 買う器（楽天・シュワブ）
    if 'SCHD_R' not in CB.CANDS:
        CB.CANDS.append('SCHD_R')


def p15_tables():
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f'p15_tab20_{P.SEED}_{P.NPATH}.npz')
    if os.path.exists(p):
        z = np.load(p)
        return {0.05: z['t05'], 0.15: z['t15']}
    t = P.dca_tables(20, [0.05, 0.15], log=True)
    np.savez_compressed(p, t05=t[0.05], t15=t[0.15])
    return t


def seat_metrics(ctx, tabs, extra_forms=None):
    """席A（QQQM 50 / SMH 20 / X 15）の全候補と、名前のある形（extra_forms）の物差し"""
    C = CB.CANDS
    base_of, worlds = ctx['base_of'], ctx['worlds']
    forms, keys = [], []
    for x in C:
        w = dict(SEAT_BASE)
        w[x] = w.get(x, 0) + SLOT
        tot = sum(w.values())
        forms.append([w.get(c, 0) / tot for c in C])
        keys.append(x)
    for nm, w in (extra_forms or {}).items():
        tot = sum(w.values())
        forms.append([w.get(c, 0) / tot for c in C])
        keys.append(nm)
    Wf = np.array(forms)
    bs = base_of(Wf)
    hs = P.hist_success(Wf, ctx['G1'], ctx['adj'], ctx['T1'])
    met = {}
    for var in IX.VARS:
        wv = worlds(Wf, bs, var)
        sig = np.sqrt(bs['q2'] if var == 'K2' else bs['q1'])
        names = wv['names']
        p15 = np.mean([P.interp(tabs[0.15], np.log1p(wv[nm]), sig) for nm in names], axis=0)
        p5 = 1 - np.mean([P.interp(tabs[0.05], np.log1p(wv[nm]), sig) for nm in names], axis=0)
        met[var] = dict(mean=wv['mean'], worst=wv['worst'], p15=p15, p5=p5, wv=wv, names=names)
    return dict(keys=keys, idx={k: i for i, k in enumerate(keys)}, met=met, vol=bs['vol'], mdd=bs['mdd'], hs=hs)


def row_of(S, k, var='main'):
    i = S['idx'][k]
    m = S['met'][var]
    d = dict(平均=round(100 * float(m['mean'][i]), 2), 最悪=round(100 * float(m['worst'][i]), 2),
             確率=round(100 * float(m['p15'][i]), 1), 五未満=round(100 * float(m['p5'][i]), 1),
             ぶれ=round(100 * float(S['vol'][i]), 1), 最大下落=round(100 * float(S['mdd'][i]), 1))
    if var == 'main':
        d['世界ごと'] = {nm: round(100 * float(m['wv'][nm][i]), 2) for nm in ('A1', 'A2', 'B', 'C')}
        d['過去20年で15%以上'] = round(100 * float(S['hs'][240][i]), 1)
        d['過去15年で15%以上'] = round(100 * float(S['hs'][180][i]), 1)
    return d


def delta(S, a, b, var):
    i, j = S['idx'][a], S['idx'][b]
    m = S['met'][var]
    return dict(平均=100 * float(m['mean'][i] - m['mean'][j]), 最悪=100 * float(m['worst'][i] - m['worst'][j]),
                確率=100 * float(m['p15'][i] - m['p15'][j]), 五未満=100 * float(m['p5'][i] - m['p5'][j]),
                ぶれ=100 * float(S['vol'][i] - S['vol'][j]), 最大下落=100 * float(S['mdd'][i] - S['mdd'][j]))


def judge(S, a, b):
    per = {}
    for var in IX.VARS:
        d = delta(S, a, b, var)
        per[var] = dict(Δ={k: round(v, 2) for k, v in d.items()}, 判定=IX.verdict(d))
    vs = {var: per[var]['判定'] for var in IX.VARS}
    return dict(感度ごと=per, 主=vs['main'], まとめ=IX.summarize(vs))


def p2_style_alt(ctx):
    """P2: B の型の上乗せを D/P 上位30% と BIG HiOP（大型×高収益）の平均に。B と C を作り直して rows を書き換える（元の値を返す）"""
    rows = ctx['rows']
    r = rows['SCHD_R']
    ff = M.ff_factors()
    mkt = ff['mkt']
    pdp = M.french_series('Portfolios_Formed_on_D-P', want='Value Weight Returns')['Hi 30']
    pop = M.french_series('6_Portfolios_ME_OP_2x3', want='Average Value Weighted Returns')['BIG HiOP']

    def x_vs(s):
        ks = sorted(k for k in s if k in mkt)
        return R.geo(s, ks) - R.geo(mkt, ks)
    x_dp, x_op = x_vs(pdp), x_vs(pop)
    assert abs(x_dp - r['B_X']) < 1e-12, ('D/P 上位30% の上乗せが etf_forward_rank と食い違う', x_dp, r['B_X'])
    x_alt = (x_dp + x_op) / 2
    b = R.R_EQ + R.SHRINK * x_alt + r['B_rec']
    c = (R.H_JPM * R.JPM['DIV'] / 100 + (R.H - R.H_JPM) * b) / R.H
    old = (r['B'], r['C'])
    r['B'] = b - r['er_vehicle'] - r['tax_drag']
    r['C'] = c - r['er_vehicle'] - r['tax_drag']
    return old, dict(x_dp=x_dp, x_op=x_op, x_alt=x_alt, B=r['B'], C=r['C'])


def p3_measured_cost():
    """楽天・シュワブ（四半期決算型）の実際の費用＝SCHD の円建ての総リターン（経費を足し戻した指数の代わり）との差（年率・直近2年の中の1年ごとの差の平均）"""
    import bestfund_vehicles as V
    V.IDX['SCHD'] = ('yahoo_er', 'SCHD', SCHD_ER)
    res = V.td_fund('SCHD', SCHD_ISIN_Q, SCHD_ASSOC_Q, 2)
    if res is None:
        return None
    td, a, b = res
    return dict(td=td, window=f'{a}〜{b}', total_cost_vs_index=-td)


def apply_p3(ctx, cost_total):
    """主の費用（実質の信託報酬＋源泉）を実測の総費用に置き換える。adj（A1・A2 の正味−費用前）と B・C を書き換え、元へ戻す値を返す"""
    rows, C = ctx['rows'], CB.CANDS
    j = C.index('SCHD_R')
    r = rows['SCHD_R']
    old = (float(ctx['adj'][j]), r['B'], r['C'])
    # A1・A2: データの器（SCHD・経費 0.06% 控除後）から、指数に対する総費用のうち SCHD の経費を除いた分を引く
    ctx['adj'][j] = -(cost_total - SCHD_ER)
    r['B'] = r['B_gross'] - cost_total
    r['C'] = r['C_gross'] - cost_total
    return old


def restore_p3(ctx, old):
    j = CB.CANDS.index('SCHD_R')
    ctx['adj'][j] = old[0]
    ctx['rows']['SCHD_R']['B'], ctx['rows']['SCHD_R']['C'] = old[1], old[2]


# ───────────────────────── 実績の表（参考） ─────────────────────────
def fx_monthly():
    fx = G.fred('DEXJPUS')
    ks = sorted(fx)
    return {k: fx[k] / fx[p] - 1 for p, k in zip(ks, ks[1:])}


def to_jpy(r, fxr):
    return {k: (1 + v) * (1 + fxr[k]) - 1 for k, v in r.items() if k in fxr}


def stats(r, ks):
    ks = [k for k in ks if k in r]
    if len(ks) < 12:
        return None
    lv, peak, mdd = 1.0, 1.0, 0.0
    for k in ks:
        lv *= 1 + r[k]
        peak = max(peak, lv)
        mdd = min(mdd, lv / peak - 1)
    g = lv ** (12 / len(ks)) - 1
    v = float(np.std([math.log1p(r[k]) for k in ks])) * math.sqrt(12)
    return dict(年率=round(100 * g, 2), ぶれ=round(100 * v, 1), 最大下落=round(100 * mdd, 1), 月数=len(ks), 最初=ks[0], 最後=ks[-1])


def year_ret(r, y, last=None):
    ks = [k for k in r if k // 100 == y and (last is None or k <= last)]
    if not ks:
        return None
    return round(100 * (float(np.prod([1 + r[k] for k in ks])) - 1), 1)


def mix(rs, w, ks):
    tot = sum(w.values())
    return {k: sum(w[t] / tot * rs[t][k] for t in w) for k in ks if all(k in rs[t] for t in w)}


def part1_reference(prof):
    fxr = fx_monthly()
    ticks = ['SCHD', 'SPY', 'QQQ', 'VYM', 'VIG', 'DGRW', 'HDV', 'NOBL', 'ITA', 'SMH', 'VEIPX']
    usd = {t: M.yahoo(t) for t in ticks}
    jpy = {t: to_jpy(usd[t], fxr) for t in ticks}
    ks = months(*W_OVL)
    rec = {}
    for t in ticks:
        own = [k for k in ks if k in usd[t]]
        rec[t] = dict(ドル=stats(usd[t], own), 円=stats(jpy[t], own),
                      暦年_ドル={str(y): year_ret(usd[t], y) for y in (2018, 2020, 2022, 2023, 2024, 2025)},
                      QQQとの相関=round(M.corr([usd[t][k] for k in own if k in usd['QQQ']], [usd['QQQ'][k] for k in own if k in usd['QQQ']]), 2),
                      SMHとの相関=round(M.corr([usd[t][k] for k in own if k in usd['SMH']], [usd['SMH'][k] for k in own if k in usd['SMH']]), 2))
        rec[t]['2026年1〜9月_ドル'] = year_ret(usd[t], 2026, 202609)
    # 同じ窓（全員がそろう 2013-11〜）の比べ
    common = [k for k in ks if all(k in usd[t] for t in ticks)]
    same = {t: dict(ドル=stats(usd[t], common), 円=stats(jpy[t], common)) for t in ticks}
    # その他15% の形（実在の値・毎月組み直し・2011-11〜・費用前の器のデータ）
    forms = {'今の形（QQQ 50 / SMH 20 / ITA 15）': {'QQQ': 50, 'SMH': 20, 'ITA': 15},
             'SCHD を入れた形（QQQ 50 / SMH 20 / SCHD 15）': {'QQQ': 50, 'SMH': 20, 'SCHD': 15},
             '半分ずつ（QQQ 50 / SMH 20 / ITA 7.5 / SCHD 7.5）': {'QQQ': 50, 'SMH': 20, 'ITA': 7.5, 'SCHD': 7.5},
             'NASDAQ100 に回した形（QQQ 65 / SMH 20）': {'QQQ': 65, 'SMH': 20}}
    shapes = {}
    for nm, w in forms.items():
        mu = mix(usd, w, ks)
        mj = mix(jpy, w, ks)
        shapes[nm] = dict(ドル=stats(mu, ks), 円=stats(mj, ks), 暦年_ドル={str(y): year_ret(mu, y) for y in (2018, 2020, 2022)},
                          最悪の12か月_ドル=round(100 * min(float(np.prod([1 + mu[k] for k in ks[i:i + 12]])) - 1 for i in range(len(ks) - 11)), 1))
    # 中身の重なり
    prof_old = json.load(open(os.path.join(BASE, 'out', 'etf_profiles.json'))).get('etfs') or {}
    H = {t: {h[0].upper(): float(h[1]) for h in (prof_old.get(t) or {}).get('h') or []} for t in ('QQQ', 'SMH', 'ITA')}
    hs = {h[0].upper(): float(h[1]) for h in prof['SCHD']['holdings'] if h[0] and h[0] != 'n/a'}
    tot = sum(hs.values())
    top = sorted(hs.items(), key=lambda kv: -kv[1])
    overlap = {'本数': len(hs), '掲載の合計(%)': round(100 * tot, 1), 'asof': prof['SCHD']['asof'],
               '上位10': [[k, round(100 * w, 2)] for k, w in top[:10]],
               'NASDAQ100 にも入っている会社(%)': round(100 * sum(w for k, w in hs.items() if k in H['QQQ']) / tot, 1),
               'NASDAQ100 にも入っている会社': [k for k, _ in top if k in H['QQQ']],
               'SMH にも入っている会社(%)': round(100 * sum(w for k, w in hs.items() if k in H['SMH']) / tot, 1),
               'SMH にも入っている会社': [k for k, _ in top if k in H['SMH']],
               'ITA にも入っている会社(%)': round(100 * sum(w for k, w in hs.items() if k in H['ITA']) / tot, 1),
               'ITA にも入っている会社': [k for k, _ in top if k in H['ITA']],
               '個別株の候補と重なる会社(%)': {k: round(100 * hs[k], 2) for k in CASTLE if k in hs},
               '業種（Alpha Vantage）': prof['SCHD']['sectors']}
    return dict(実績=rec, 同じ窓_全員がそろう月=dict(窓=f'{common[0]}〜{common[-1]}', 表=same), 形=shapes, 重なり=overlap)


# ───────────────────────── 第2部 ─────────────────────────
def jita_rows():
    return json.load(open(JITA, encoding='utf-8'))['rows']


def nfkc(s):
    return unicodedata.normalize('NFKC', s or '')


def jita_monthly(isin, assoc):
    import bestfund_data as D
    rows = D.jita_daily(isin, assoc)
    lv, x, last = {}, 1.0, {}
    prev = None
    for d, n, v in rows:
        if prev is not None:
            x *= (n + v) / prev
        prev = n
        last[d // 100] = x
    ks = sorted(last)
    return {k: last[k] / last[p] - 1 for p, k in zip(ks, ks[1:]) if (k // 100 * 12 + k % 100) - (p // 100 * 12 + p % 100) == 1}


FAMILY_PAT = [r'メガ10', r'S&P500トップ10', r'FANG\+', r'テクノロジー株式集中', r'USテック・トップ20', r'NASDAQトップ30', r'S&P500トップ20',
              r'QQQメガ', r'NASDAQ次世代', r'NASDAQ100インデックス$']
FAMILY_EX = re.compile(r'(レバレッジ|ゴールド|毎月決算|予想分配)')


def family_table_jp():
    out = []
    for r in jita_rows():
        nm = nfkc(r['fundNm'])
        if str(r.get('dcFundFlg')) == '1' or FAMILY_EX.search(nm):
            continue
        if not any(re.search(p, nm) for p in FAMILY_PAT):
            continue
        if nm.startswith('FANG+インデックス・オープン'):
            pass
        info = r.get('institutionInfo') or []
        if isinstance(info, str):
            try:
                info = json.loads(info)
            except Exception:
                info = []
        rak = next((x for x in info if isinstance(x, dict) and '楽天証券' in json.dumps(x, ensure_ascii=False)), None)
        is_etf = str(r.get('fundCategory')) == '10'
        try:
            fee = round(float(r['trustReward']) * 1.1, 4)
        except (TypeError, ValueError):
            fee = None
        tsumi = str(r.get('nisaFlg')) == '1'
        grow = str(r.get('nisaGrowthFlg')) == '1'
        out.append(dict(名前=nm, 種類='東証ETF' if is_etf else '投信', 設定日=(r.get('establishedDate') or '')[:10],
                        信託報酬_税込=fee, NISA=('つみたて・成長' if tsumi and grow else '成長' if grow else 'つみたて' if tsumi else '対象外（または表示が遅れている）'),
                        純資産_億円=round(float(r['totalNetAssets']) / 100, 1) if r.get('totalNetAssets') else None,
                        楽天で買える=bool(rak) or is_etf, 騰落率1年=r.get('standardPriceRa1y'), 騰落率3年=r.get('standardPriceRa3y'),
                        isin=r.get('isinCd'), assoc=r.get('associFundCd')))
    out.sort(key=lambda x: (x['設定日'] or ''))
    return out


def part2(prof):
    fxr = fx_monthly()
    ticks = ['^NYFANG', 'QQQ', 'SPY', 'MGK', 'XLG', 'OEF', 'VUG', 'MGC', 'MAGS']
    usd = {t: M.yahoo(t) for t in ticks}
    jpy = {t: to_jpy(usd[t], fxr) for t in ticks}
    wins = {'W1 2017-10〜（FANG+ の公表後）': (201710, 202609, ['^NYFANG', 'QQQ', 'SPY', 'MGK', 'XLG', 'OEF']),
            'W2 2008-01〜': (200801, 202609, ['MGK', 'XLG', 'OEF', 'QQQ', 'SPY', 'VUG', 'MGC']),
            'W3 2000-11〜（ITバブルの崩壊を含む）': (200011, 202609, ['OEF', 'QQQ', 'SPY'])}
    W = {}
    for nm, (a, b, ts) in wins.items():
        ks = months(a, b)
        tab = {}
        for t in ts:
            tab[t] = dict(ドル=stats(usd[t], ks), 円=stats(jpy[t], ks))
            if nm.startswith('W1'):
                tab[t]['暦年_ドル'] = {str(y): year_ret(usd[t], y) for y in range(2018, 2026)}
                tab[t]['2026年1〜9月_ドル'] = year_ret(usd[t], 2026, 202609)
        W[nm] = tab
    # 形の例（W1・円・毎月組み直し）
    ks = months(201710, 202609)
    rs = {'QQQ': jpy['QQQ'], 'FANG': jpy['^NYFANG'], 'SMH': to_jpy(M.yahoo('SMH'), fxr), 'ITA': to_jpy(M.yahoo('ITA'), fxr)}
    shapes = {}
    for nm, w in {'今の形（QQQ 50 / SMH 20 / ITA 15）': {'QQQ': 50, 'SMH': 20, 'ITA': 15},
                  'NASDAQ100 の15を FANG+ に（QQQ 35 / FANG+ 15 / SMH 20 / ITA 15）': {'QQQ': 35, 'FANG': 15, 'SMH': 20, 'ITA': 15},
                  'ITA を FANG+ に（QQQ 50 / FANG+ 15 / SMH 20）': {'QQQ': 50, 'FANG': 15, 'SMH': 20}}.items():
        shapes[nm] = stats(mix(rs, w, ks), ks)
    # 投信の基準価額（実在の器・円・分配金込み）
    funds = {'iFreeNEXT FANG+インデックス': ('JP90C000FZD4', '04311181'), 'iFreeNEXT NASDAQ100インデックス': ('JP90C000GUN2', '04317188')}
    sp = next((r for r in jita_rows() if nfkc(r['fundNm']).replace(' ', '').startswith('eMAXISSlim米国株式(S&P500)')), None)
    if sp:
        funds['eMAXIS Slim 米国株式(S&P500)'] = (sp['isinCd'], sp['associFundCd'])
    fm = {nm: jita_monthly(*v) for nm, v in funds.items()}
    a = max(min(fm[nm]) for nm in fm)
    kf = [k for k in months(a, 202609) if all(k in fm[nm] for nm in fm)]
    fund_tab = {nm: stats(fm[nm], kf) for nm in fm}
    # 集中の度合い（ETF 側のお金のうちメガ10の10社に入る割合）＝事前登録。FANG+・テック12 と1社の最大（NVDA）は事後の参考
    prof_old = json.load(open(os.path.join(BASE, 'out', 'etf_profiles.json'))).get('etfs') or {}
    H = {t: {h[0].upper(): float(h[1]) for h in (prof_old.get(t) or {}).get('h') or []} for t in ('QQQ', 'SMH', 'ITA')}
    for t in H:                                   # GOOGL と GOOG は同じ会社として GOOGL に寄せる
        if 'GOOG' in H[t]:
            H[t]['GOOGL'] = H[t].get('GOOGL', 0.0) + H[t].pop('GOOG')
    norm = {t: sum(H[t].values()) for t in H}

    def etf_share(t, names):
        return sum(w for k, w in H[t].items() if k in names) / norm[t]

    def money_share(names, fund_w=None, replace=None):
        """ETF 側（NASDAQ100 50 / SMH 20 / ITA 15）のお金のうち names に入る割合。fund_w＝足す器の中身の重み、replace＝'NDX'（NASDAQ100 の15を替える）か 'ITA'"""
        w = {'QQQ': 50, 'SMH': 20, 'ITA': 15}
        extra = 0.0
        if replace == 'NDX':
            w['QQQ'] = 35
        elif replace == 'ITA':
            w['ITA'] = 0
        if replace:
            extra = 15 * sum(v for k, v in fund_w.items() if k in names)
        return round(100 * (sum(w[t] * etf_share(t, names) for t in w) + extra) / 85, 1)
    mega = [t.upper() for t in prof['MEGA10']['constituents']]
    mega_w = {t: 0.10 for t in mega}
    conc = {'メガ10の10社': mega, 'asof': prof['MEGA10'].get('asof'), '出典': prof['MEGA10'].get('src'),
            'NASDAQ100 の中の10社の比重(%)': round(100 * etf_share('QQQ', mega), 1), 'SMH の中(%)': round(100 * etf_share('SMH', mega), 1),
            'ITA の中(%)': round(100 * etf_share('ITA', mega), 1),
            'NASDAQ100 に入っていない会社': [t for t in mega if t not in H['QQQ']],
            'ETF 側のお金のうち10社に入る割合(%)': {
                '今の形（NASDAQ100 50 / SMH 20 / ITA 15）': money_share(mega),
                'NASDAQ100 の15をメガ10に（35 / メガ10 15 / 20 / 15）': money_share(mega, mega_w, 'NDX'),
                'ITA をメガ10に（50 / 20 / メガ10 15）': money_share(mega, mega_w, 'ITA')},
            '注': 'NASDAQ100・SMH・ITA の中身は out/etf_profiles.json（2026-08-19）。GOOGL と GOOG は同じ会社として数えた'}
    post = {}
    for key, fw in (('FANG+（等金額10社）', {t: 0.10 for t in prof['FANG_PLUS']['constituents']}),
                    ('テック12（12%×7・3.2%×5）', {k.upper(): v for k, v in prof['TECH12']['weights_review'].items()})):
        names = set(fw)
        post[key] = {'NASDAQ100 の中の比重(%)': round(100 * etf_share('QQQ', names), 1),
                     'NASDAQ100 に入っていない会社': sorted(t for t in names if t not in H['QQQ']),
                     '今の形': money_share(names), 'NASDAQ100 の15を替えた形': money_share(names, fw, 'NDX'), 'ITA を替えた形': money_share(names, fw, 'ITA')}
    nv = {'今の形': money_share({'NVDA'})}
    for key, fw in (('メガ10', mega_w), ('FANG+', {t: 0.10 for t in prof['FANG_PLUS']['constituents']}),
                    ('テック12', {k.upper(): v for k, v in prof['TECH12']['weights_review'].items()})):
        nv[f'NASDAQ100 の15を{key}に'] = money_share({'NVDA'}, fw, 'NDX')
    conc['事後（参考）FANG+・テック12 の同じ物差し'] = post
    conc['事後（参考）NVDA 1社の割合(%)'] = nv
    tp = json.load(open(os.path.join(BASE, 'out', 'tech_persist.json')))
    base_rate = {'tech_persist ③（時価総額の最大の1割・CRSP 1926〜）': tp['Q2_最大の1割−市場(%/年)'], '直近10年の最大の1割−市場(%/年)': tp['今の位置'].get('最大の1割−市場 直近10年%/年'),
                 'Dimensional Quick Take（CRSP 1927–2025・初めて米国の上位10社に入った会社・S&P500 との年率の差）': {
                     '10年前': 12.0, '5年前': 20.3, '3年前': 27.2, '入った後3年': 0.3, '入った後5年': -1.7, '入った後10年': -1.6,
                     '社数': '前 44/43/34・後 58/56/50（3/5/10年）', '出典': 'https://www.dimensional.com/chmedia/394308/source/download/dimensional-quick-takes.pdf（Think Twice About Chasing the Biggest Stocks）',
                     '注': '初めて入った会社の平均＝上位10社を持ち続ける器の成績そのものではない'}}
    return dict(窓=W, 形の例_W1_円=shapes, 投信の基準価額=dict(窓=f'{kf[0]}〜{kf[-1]}', 表=fund_tab), 集中の度合い=conc, 基礎率=base_rate,
                器の一覧_日本=family_table_jp(), 米国ETF=prof.get('US_ETFS'))


# ───────────────────────── 本体 ─────────────────────────
def main():
    t0 = time.time()
    prof = load_profiles()
    proxy, pick = pick_proxy()
    other = [k for k in PROXIES if k != proxy][0]
    print(f'代理: 主 {proxy}（{pick}）', flush=True)
    register(proxy, prof)
    ctx = CB.build(max_k=1)
    print(f'4つの世界（{time.time() - t0:.0f}秒）', flush=True)
    rows = ctx['rows']
    tabs = p15_tables()
    print(f'積立の表（{time.time() - t0:.0f}秒）', flush=True)
    split = {'半分ずつ（ITA 7.5 / SCHD 7.5）': {'QQQM': 50, 'SMH': 20, 'ITA': 7.5, 'SCHD_R': 7.5}}
    S = seat_metrics(ctx, tabs, split)

    # 自己検問: SCHD を足しても ITA・NASDAQ100 の席Aの数字は etf_ita_xlk.json と同じ
    ixj = json.load(open(os.path.join(BASE, 'out', 'etf_ita_xlk.json')))
    tabA = ixj['席']['A']['table'] if '席' in ixj else ixj['slots']['A']['table']
    for x in ('ITA', 'QQQM', 'XLK'):
        mine = row_of(S, x)
        for k in ('平均', '最悪', '確率', 'ぶれ', '最大下落'):
            assert abs(mine[k] - tabA[x][k]) < 0.011, ('席Aの数字が etf_ita_xlk.json と食い違う', x, k, mine[k], tabA[x][k])

    C = CB.CANDS
    mm = S['met']['main']
    order = {lab: sorted(C, key=lambda x: -float(mm[key][S['idx'][x]])) for lab, key in (('平均', 'mean'), ('最悪', 'worst'), ('確率', 'p15'))}
    table = {x: row_of(S, x) for x in C}
    J1 = judge(S, 'SCHD_R', 'QQQM')
    J2 = judge(S, 'SCHD_R', 'ITA')
    J_ITA = judge(S, 'ITA', 'QQQM')
    for var in IX.VARS:
        J1['感度ごと'][var].update(X=row_of(S, 'SCHD_R', var), NASDAQ100=row_of(S, 'QQQM', var))
        J2['感度ごと'][var].update(SCHD=row_of(S, 'SCHD_R', var), ITA=row_of(S, 'ITA', var))
    print(f'J1 {J1["主"]}/{J1["まとめ"]}  J2 {J2["主"]}/{J2["まとめ"]}（{time.time() - t0:.0f}秒）', flush=True)

    # ── SCHD だけの感度 ──
    sens = {}
    old, p2 = p2_style_alt(ctx)
    S2_ = seat_metrics(ctx, tabs)
    sens['P2 B の型を D/P 上位30% と BIG HiOP の平均に'] = dict(J1=judge(S2_, 'SCHD_R', 'QQQM'), J2=judge(S2_, 'SCHD_R', 'ITA'),
                                                       SCHD=row_of(S2_, 'SCHD_R'), 上乗せ={k: round(100 * v, 2) for k, v in p2.items()})
    rows['SCHD_R']['B'], rows['SCHD_R']['C'] = old
    p3 = p3_measured_cost()
    if p3:
        o3 = apply_p3(ctx, p3['total_cost_vs_index'])
        S3_ = seat_metrics(ctx, tabs)
        sens['P3 費用を楽天・シュワブ（四半期決算型）の実測に'] = dict(J1=judge(S3_, 'SCHD_R', 'QQQM'), J2=judge(S3_, 'SCHD_R', 'ITA'),
                                                              SCHD=row_of(S3_, 'SCHD_R'),
                                                              実測=dict(窓=p3['window'], 指数に対する総費用_年率=round(100 * p3['total_cost_vs_index'], 3),
                                                                      主の総費用_年率=round(100 * (VEH_ER + 0.10 * prof['SCHD']['dy']), 3)))
        restore_p3(ctx, o3)
    else:
        sens['P3 費用を楽天・シュワブ（四半期決算型）の実測に'] = '測れない（記録が足りない）'
    main_rows = {k: dict(rows['SCHD_R']) for k in ('SCHD_R',)}
    # P1 は代理を替えて作り直す（最後に回す＝主の ctx を壊さない）
    R.DATA['SCHD_R'] = ('SCHD', other, 201110)
    ctx1 = CB.build(max_k=1)
    S1_ = seat_metrics(ctx1, tabs)
    sens['P1 代理をもう一方に'] = dict(代理=other, J1=judge(S1_, 'SCHD_R', 'QQQM'), J2=judge(S1_, 'SCHD_R', 'ITA'), SCHD=row_of(S1_, 'SCHD_R'),
                                   A1=round(100 * ctx1['rows']['SCHD_R']['A1'], 2))
    R.DATA['SCHD_R'] = ('SCHD', proxy, 201110)
    print(f'感度（{time.time() - t0:.0f}秒）', flush=True)

    r = main_rows['SCHD_R']
    one = {k: (round(100 * r[k], 2) if isinstance(r.get(k), float) else r.get(k)) for k in
           ('A1', 'A2', 'B', 'C', 'A1_gross', 'A2_gross', 'er_vehicle', 'er_data', 'dy_vehicle', 'tax_drag', 'B_X', 'B_rec', 'B_src',
            'record_share_e', 'top_industries', 'vol_A1', 'maxdd_A1', 'vol_A2', 'maxdd_A2')}
    ref1 = part1_reference(prof)
    print(f'第1部の参考（{time.time() - t0:.0f}秒）', flush=True)
    p2_ = part2(prof) if prof['MEGA10']['constituents'] else None
    print(f'第2部（{time.time() - t0:.0f}秒）', flush=True)

    if J2['まとめ'] == '堅い価値あり':
        concl = 'ITA を SCHD に替える根拠あり（J2 が堅い価値あり）'
    elif J2['まとめ'] == '堅い価値なし〜小さい':
        concl = 'ITA のまま（J2 が堅い価値なし〜小さい）'
    else:
        concl = 'ITA のまま（J2 が前提しだい＝替える根拠は堅くない）'
    doc = {
        'generated': datetime.date.today().isoformat(), 'tool': 'night/morefunds.py', 'prereg': PREREG,
        'question': 'メガ10のほかの候補と、SCHD をその他15%に入れる価値（ITA を替えるか）',
        '第1部_SCHD': {
            '結論（事前登録の決まりどおり）': concl,
            '代理の選び方': dict(主=proxy, 候補=pick, 決まり='2011-11〜2026-09 の月次の相関が高いほう（同点なら VEIPX）'),
            'SCHD_R 1本の数字（%/年・費用と源泉の後）': one,
            '席A 今の形のその他15%（QQQM 50 / SMH 20 / X 15）': dict(表=table, 順位={x: {lab: order[lab].index(x) + 1 for lab in order} for x in C},
                                                          上位5={lab: order[lab][:5] for lab in order}),
            'J1 SCHD を入れる価値（SCHD − NASDAQ100）': J1,
            'J2 ITA を SCHD に替えるか（SCHD − ITA）': J2,
            '参考 ITA − NASDAQ100（etf_ita_xlk と同じ数字になるはず）': J_ITA,
            '参考 半分ずつの形': row_of(S, '半分ずつ（ITA 7.5 / SCHD 7.5）'),
            'SCHD だけの感度': sens,
            '実績と重なり（参考・判定に使わない）': ref1,
        },
        '第2部_メガ10の仲間': p2_,
        '⚠': [
            'SCHD の実績は2011年からの15年。A1 の2000〜2011年は代理（実在の投信か French）で、SCHD の今の作り方（質のふるい）とは違う',
            '4つの世界の B・C は仮定（100年の平均の型の上乗せを半分に縮める・JPM の予想）。重みは同じと置いた',
            'メガ10の指数の公表後の記録は1年、FANG+ は9年。上位10社の集中の長い実績はこのリポジトリに無い',
            '^NYFANG は価格指数（配当を含まない）＝FANG+ の年率は配当の分（年0.3%前後）だけ低く出る',
            '判定・配分には使わない（材料）。配分を変えるかはユーザーの判断',
        ],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f'書いた: {OUT}（{time.time() - t0:.0f}秒）')


def main_part2():
    """第2部だけ作り直して out/morefunds.json に入れる（第1部は書き換えない）"""
    prof = load_profiles()
    doc = json.load(open(OUT, encoding='utf-8'))
    doc['第2部_メガ10の仲間'] = part2(prof)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f'書いた（第2部）: {OUT}')


if __name__ == '__main__':
    if '--part2' in sys.argv:
        main_part2()
    else:
        main()
