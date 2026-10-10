#!/usr/bin/env python3
"""night/etf_forward_rank.py — これからの最強のETF（楽天で買える25本）を4つの世界の今後の年率で並べる（2026-10-10・ユーザー指示）

読むだけ。門・採点・配分には触れない。事前登録 out/etf_forward_prereg.json（b6b8f1c・測る前に固定）どおりに計算する。

  A1 直近26年がもう一度来る世界 … 月次リターン 2000-09→2026-09 の幾何年率（代理つなぎ・Yahoo の月足・配当込み）
  A2 直近15年の流れが続く世界   … 2011-10→2026-09 の幾何年率
  B  100年の平均に戻る世界       … R株 8.04%（UBS 2026: 先進国株 実質5.44%＋インフレ2.5%）＋0.5×X（French の業種・型の長い歴史の上乗せ）
                                     ＋REC（米国の候補だけ・記録の二業種〔ソフトウェア＋半導体・電子部品〕の比率 e で 0.204−0.52e）／金 3.83%
  C  今の値段が効く世界           … J.P. Morgan 2026 LTCMA の複利の予想を種類に当て、12.5年の後は B に戻る: (12.5×JPM＋7.5×B)/20
単位はドル建ての幾何年率。費用（買う器の経費率）と NISA の中で取り戻せない配当の外国税（k×配当利回り）を引いた後。
順位は4つの世界の単純平均。同点は最悪の世界が高いほう。

出力: out/etf_forward_rank.json（入力の ETF の中身の写真は out/etf_forward_profiles.json と out/etf_profiles.json）
"""
import datetime, json, math, os, sys, statistics as S

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import mw_common as M                                   # noqa: E402
from industry_exposure import sic_lookup, FRENCH_LIKE   # noqa: E402
from industry_trends import ff49_map                    # noqa: E402

OUT = os.path.join(BASE, 'out', 'etf_forward_rank.json')
PREREG = 'out/etf_forward_prereg.json（b6b8f1c）'
A1, A2 = (200009, 202609), (201110, 202609)
H, H_JPM, H_GMO, H_VG = 20, 12.5, 7, 10
SHRINK = 0.5
INFL = 0.025
R_EQ = (1 + 0.0544) * (1 + INFL) - 1        # UBS 2026: 先進国株 名目8.5%・インフレ2.9% → 実質5.44%
R_GOLD = (1 + 0.013) * (1 + INFL) - 1       # UBS 2026: 金の実質 1.3%/年
REC_A, REC_B = 0.00204, 0.0052               # REC = 0.204% − 0.52%×e（industry_peak の20年先: 記録 −1.01・比較群 −0.49）
E_MKT = 0.392                                # 米国市場の記録の二業種の比重（industry_peak の 2025年末: ソフトウェア19.9＋半導体・電子部品19.3）

# ── 候補（事前登録の list と同じ順・同じ中身） ──
C = {
    'VT':    dict(ja='全世界株', veh='VT（または eMAXIS Slim 全世界株式）', us=False, k=0.62 * 0.10 + 0.38 * 0.20),
    'VOO':   dict(ja='S&P500', veh='VOO（または eMAXIS Slim 米国株式 S&P500）', us=True, k=0.10),
    'VEA':   dict(ja='先進国株（米国除く）', veh='VEA', us=False, k=0.20),
    'VWO':   dict(ja='新興国株', veh='VWO', us=False, k=0.20),
    'TOPIX': dict(ja='日本株（TOPIX）', veh='東証の TOPIX 連動ETF（1306・1348・2557 など）', us=False, k=0.0),
    'EPI':   dict(ja='インド株', veh='EPI', us=False, k=0.20),
    'QQQM':  dict(ja='NASDAQ100', veh='QQQM（または iFreeNEXT NASDAQ100）', us=True, k=0.10),
    'VUG':   dict(ja='米国大型グロース', veh='VUG', us=True, k=0.10),
    'XLK':   dict(ja='米国テクノロジー', veh='XLK', us=True, k=0.10),
    'SMH':   dict(ja='半導体', veh='SMH', us=True, k=0.10),
    'XLV':   dict(ja='米国ヘルスケア', veh='XLV', us=True, k=0.10),
    'XLP':   dict(ja='米国生活必需品', veh='XLP', us=True, k=0.10),
    'XLU':   dict(ja='米国公益（電力）', veh='XLU', us=True, k=0.10),
    'XLE':   dict(ja='米国エネルギー', veh='XLE', us=True, k=0.10),
    'ITA':   dict(ja='米国航空・防衛', veh='ITA', us=True, k=0.10),
    'VTV':   dict(ja='米国大型バリュー', veh='VTV', us=True, k=0.10),
    'VBR':   dict(ja='米国小型バリュー', veh='VBR', us=True, k=0.10),
    'IJR':   dict(ja='米国小型（S&P600）', veh='IJR', us=True, k=0.10),
    'VIG':   dict(ja='米国連続増配', veh='VIG', us=True, k=0.10),
    'VYM':   dict(ja='米国高配当', veh='VYM', us=True, k=0.10),
    'MOAT':  dict(ja='米国ワイドモート（質）', veh='MOAT', us=True, k=0.10),
    'RSP':   dict(ja='S&P500 均等加重', veh='RSP', us=True, k=0.10),
    'PXF':   dict(ja='先進国（米国除く）バリュー寄り', veh='PXF', us=False, k=0.20),
    'DEM':   dict(ja='新興国高配当（バリュー寄り）', veh='DEM', us=False, k=0.20),
    'GLDM':  dict(ja='金', veh='GLDM', us=False, k=0.0),
}
# データの器（A1・A2 の価格）: {候補: (主のティッカー, 代理, 代理を使う最後の月)}
DATA = {
    'VT': ('VT', 'BLEND_VTSMX_VGTSX', 200806), 'VOO': ('SPY', None, None), 'VEA': ('VEA', 'VTMGX', 200707),
    'VWO': ('VWO', 'VEIEX', 200503), 'TOPIX': ('EWJ', None, None), 'EPI': ('EPI', None, None), 'QQQM': ('QQQ', None, None),
    'VUG': ('VUG', 'VIGRX', 200401), 'XLK': ('XLK', None, None), 'SMH': ('SMH', None, None), 'XLV': ('XLV', None, None),
    'XLP': ('XLP', None, None), 'XLU': ('XLU', None, None), 'XLE': ('XLE', None, None), 'ITA': ('ITA', 'FSDAX', 200605),
    'VTV': ('VTV', 'VIVAX', 200401), 'VBR': ('VBR', 'VISVX', 200401), 'IJR': ('IJR', None, None), 'VIG': ('VIG', None, None),
    'VYM': ('VYM', None, None), 'MOAT': ('MOAT', 'FRENCH_BIG_HIOP', 201204), 'RSP': ('RSP', None, None),
    'PXF': ('PXF', 'DFIVX', 200706), 'DEM': ('DEM', 'DFEVX', 200707), 'GLDM': ('GLD', 'GOLD_FUT', 200412),
}
SAME_WINDOW = {'EPI', 'VIG', 'VYM', 'RSP'}   # 2000年より後に始まる＝A1 は同じ窓の SPY との差で
TOPIX_ER = 0.0006                            # 東証の TOPIX 連動ETF の経費率と置く（事前登録）
MOAT_ER = 0.0046                             # MOAT の経費率（out/etf_profiles.json）＝French の代理の期間に引く
MIN_SHARE = 0.0025                           # 業種の長い歴史を測る月の下限（米国株の時価総額に占める比重）＝結果を見た後の是正
# JPM 2026 LTCMA（USD・複利・%）
JPM = {'ACWI': 7.0, 'USL': 6.7, 'USS': 6.9, 'EAFE': 7.5, 'JP': 8.8, 'EM': 7.8, 'ASIAxJ': 7.9,
       'VALUE': 7.7, 'QUALITY': 6.6, 'DIV': 7.5, 'GOLD': 5.5}
JPM_MAP = {'VT': 'ACWI', 'VOO': 'USL', 'VEA': 'EAFE', 'VWO': 'EM', 'TOPIX': 'JP', 'EPI': 'ASIAxJ',
           'QQQM': 'USL', 'VUG': 'USL', 'XLK': 'USL', 'SMH': 'USL', 'XLV': 'USL', 'XLP': 'USL', 'XLU': 'USL', 'XLE': 'USL',
           'ITA': 'USL', 'RSP': 'USL', 'VTV': 'VALUE', 'VBR': 'USS', 'IJR': 'USS', 'VIG': 'QUALITY', 'MOAT': 'QUALITY',
           'VYM': 'DIV', 'PXF': 'EAFE', 'DEM': 'EM', 'GLDM': 'GOLD'}
# GMO 7年・実質（2026-08-31・通常金利と低金利の中点）＝感度 S4 だけで使う
GMO = {'USL': (-7.4 + -4.3) / 2, 'USS': (-5.8 + -2.8) / 2, 'USDV': (-0.7 + 1.2) / 2, 'INTL': (-1.5 + 0.9) / 2,
       'INTLS': (0.8 + 3.2) / 2, 'INTLDV': (3.0 + 4.4) / 2, 'JPSV': (4.7 + 6.4) / 2, 'EM': (-0.1 + 1.6) / 2, 'EMV': (3.3 + 4.4) / 2}
GMO_MAP = {'VT': [('USL', .62), ('INTL', .28), ('EM', .10)], 'VOO': [('USL', 1)], 'VEA': [('INTL', 1)], 'VWO': [('EM', 1)],
           'TOPIX': [('INTL', 1)], 'EPI': [('EM', 1)], 'QQQM': [('USL', 1)], 'VUG': [('USL', 1)], 'XLK': [('USL', 1)],
           'SMH': [('USL', 1)], 'XLV': [('USL', 1)], 'XLP': [('USL', 1)], 'XLU': [('USL', 1)], 'XLE': [('USL', 1)],
           'ITA': [('USL', 1)], 'RSP': [('USL', 1)], 'VIG': [('USL', 1)], 'MOAT': [('USL', 1)],
           'VTV': [('USL', .5), ('USDV', .5)], 'VYM': [('USL', .5), ('USDV', .5)], 'VBR': [('USS', .5), ('USDV', .5)],
           'IJR': [('USS', 1)], 'PXF': [('INTL', .5), ('INTLDV', .5)], 'DEM': [('EMV', 1)], 'GLDM': None}
# Vanguard VCMM（2026-06-30・10年・名目の範囲の中点）＝感度 S4 だけで使う
VG = {'US': 5.2, 'DEV': 5.5, 'EM': 3.0}
VG_MAP = {'VT': [('US', .62), ('DEV', .28), ('EM', .10)], 'VEA': [('DEV', 1)], 'TOPIX': [('DEV', 1)], 'PXF': [('DEV', 1)],
          'VWO': [('EM', 1)], 'EPI': [('EM', 1)], 'DEM': [('EM', 1)], 'GLDM': None}


def months(a, b):
    out, y, m = [], a // 100, a % 100
    while y * 100 + m <= b:
        out.append(y * 100 + m)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def geo(r, ks):
    """月次リターン r の ks の幾何年率（小数）。ks に欠けがあれば None（欠測を0と読まない）"""
    if not ks or any(k not in r for k in ks):
        return None
    lg = sum(math.log1p(r[k]) for k in ks)
    return math.exp(lg * 12 / len(ks)) - 1


def vol(r, ks):
    xs = [r[k] for k in ks if k in r]
    return S.pstdev(xs) * math.sqrt(12) if len(xs) > 12 else None


def maxdd(r, ks):
    v, pk, dd = 1.0, 1.0, 0.0
    for k in ks:
        if k not in r:
            continue
        v *= 1 + r[k]
        pk = max(pk, v)
        dd = min(dd, v / pk - 1)
    return dd


def gold_futures_monthly():
    """金先物 GC=F の日足の月末の終値 → 月次リターン（月足は抜けがあるので使わない）"""
    import time as _t
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/GC=F?period1=946684800&period2={int(_t.time())}&interval=1d'
    j = json.loads(M.get(u, name='yh_GC_F_1d_raw.json', max_age_days=3))
    r = j['chart']['result'][0]
    mon = {}
    for t, c in zip(r['timestamp'], r['indicators']['quote'][0]['close']):
        if c is None:
            continue
        d = datetime.datetime.utcfromtimestamp(t)
        mon[d.year * 100 + d.month] = c
    ks = sorted(mon)
    return {k: mon[k] / mon[p] - 1 for p, k in zip(ks, ks[1:]) if months(p, k)[1:2] == [k]}


def french_vw(name, col, want='Value Weight'):
    return M.french_series(name, want=want)[col]


def build_chains(log):
    """候補ごとの月次リターン（データの器）と、つなぎ目の相関の点検"""
    cache = {}

    def y(t):
        if t not in cache:
            cache[t] = M.yahoo(t)
        return cache[t]
    chains, checks = {}, {}
    big_hiop = french_vw('6_Portfolios_ME_OP_2x3', 'BIG HiOP', want='Average Value Weighted Returns')
    for c, (main, proxy, last) in DATA.items():
        r = dict(y(main))
        if proxy:
            if proxy == 'BLEND_VTSMX_VGTSX':
                a, b = y('VTSMX'), y('VGTSX')
                p = {k: 0.5 * a[k] + 0.5 * b[k] for k in a if k in b}
            elif proxy == 'FRENCH_BIG_HIOP':
                p = {k: v - MOAT_ER / 12 for k, v in big_hiop.items()}   # French の期間は MOAT の費用を引く（事前登録）
            elif proxy == 'GOLD_FUT':
                p = gold_futures_monthly()
            else:
                p = y(proxy)
            ov = [k for k in r if k in p and k > last]
            if len(ov) >= 24:
                checks[c] = {'proxy': proxy, 'overlap_months': len(ov), 'corr': round(M.corr([r[k] for k in ov], [p[k] for k in ov]), 3),
                             'geo_main': round(geo(r, sorted(ov)) * 100, 2), 'geo_proxy': round(geo(p, sorted(ov)) * 100, 2)}
            for k, v in p.items():
                if k <= last:
                    r[k] = v
            for k in [k for k in r if k <= last and k not in p]:
                del r[k]
        chains[c] = r
    spy = y('SPY')
    return chains, checks, spy


def holdings_of(t, prof_old, prof_new):
    if t in prof_new:
        return [(h[0], h[1]) for h in prof_new[t].get('holdings') or [] if h and h[0] and h[0] != 'n/a']
    if t in prof_old:
        return [(h[0], h[1]) for h in prof_old[t].get('h') or []]
    return []


def main():
    log = []
    prof_old = (json.load(open(os.path.join(BASE, 'out', 'etf_profiles.json'))).get('etfs') or {})
    pnew_path = os.path.join(BASE, 'out', 'etf_forward_profiles.json')
    prof_new = (json.load(open(pnew_path)).get('etfs') or {}) if os.path.exists(pnew_path) else {}

    # ── 費用と配当利回り（買う器） ──
    def er_dy(t):
        if t == 'TOPIX':
            return TOPIX_ER, None
        src = prof_new.get(t) or prof_old.get(t) or {}
        er = src.get('er'); dy = src.get('dy')
        return (float(er) if er is not None else None), (float(dy) if dy is not None else None)
    data_er = {}
    for c, (main, _, _) in DATA.items():
        src = prof_new.get(main) or prof_old.get(main) or {}
        data_er[c] = src.get('er')
    # データの器が候補と違うもの（AV に無ければ公表値を置く: SPY 0.0945%・EWJ 0.50%・GLD 0.40%）
    data_er['VOO'] = data_er.get('VOO') or 0.000945
    data_er['TOPIX'] = 0.0050
    data_er['GLDM'] = 0.0040

    chains, checks, spy = build_chains(log)
    k1, k2 = months(*A1), months(*A2)
    spy_a1 = geo(spy, k1)

    rows = {}
    for c, meta in C.items():
        r = chains[c]
        ks_all = sorted(k for k in r if k <= A1[1])
        a1 = geo(r, k1)
        a1_note = None
        if c in SAME_WINDOW:
            own = [k for k in ks_all if k >= ks_all[0]]
            g_c, g_s = geo(r, own), geo(spy, own)
            a1 = spy_a1 + (g_c - g_s)
            a1_note = f'{own[0]}〜{own[-1]}（{len(own) / 12:.1f}年）の SPY との差 {100 * (g_c - g_s):+.2f}%/年 を SPY の A1 に足した'
        a2 = geo(r, k2)
        rows[c] = dict(ja=meta['ja'], vehicle=meta['veh'], data=DATA[c][0], proxy=DATA[c][1], proxy_until=DATA[c][2],
                       A1_gross=a1, A2_gross=a2, A1_note=a1_note,
                       vol_A1=vol(r, k1 if c not in SAME_WINDOW else ks_all), maxdd_A1=maxdd(r, k1 if c not in SAME_WINDOW else ks_all),
                       vol_A2=vol(r, k2), maxdd_A2=maxdd(r, k2))

    # ── 世界B ──
    ff = M.ff_factors()
    mkt = ff['mkt']
    ind = M.french_series('49_Industry_Portfolios', want='Average Value Weighted Returns')
    # ★結果を見た後の是正（データの質・事前登録の外）: 業種の長い歴史は、その業種が米国株の時価総額の
    # MIN_SHARE 以上ある月だけで測る。事前登録の『使える全期間』のままだと Softw は 1965-07〜1982 に
    # 1社しかなく（1960年代 −20%/年・1970〜80年代 −15%/年）、業種の基礎率ではなく1社の値動きになっていた
    # （Softw の上乗せ −4.68%/年）。事前登録どおりの値は X_ind_raw に残し、感度 S0 で順位を並べる。
    tabs49 = M.french_tables('49_Industry_Portfolios')
    nf = next(v for k, v in tabs49.items() if k.startswith('Number of Firms') and v['freq'] == 'monthly')
    sz = next(v for k, v in tabs49.items() if k.startswith('Average Firm Size') and v['freq'] == 'monthly')
    share = {}
    for d, row in nf['data'].items():
        srow = sz['data'].get(d)
        if not srow:
            continue
        caps = [(n or 0) * (z or 0) if (n and z and n > 0 and z > 0) else 0 for n, z in zip(row, srow)]
        tot = sum(caps)
        if tot:
            share[d] = {c: caps[i] / tot for i, c in enumerate(nf['cols'])}
    X_ind, X_ind_raw = {}, {}
    for nm, s in ind.items():
        ks = sorted(k for k in s if k in mkt)
        if len(ks) >= 240:
            X_ind_raw[nm] = dict(x=geo(s, ks) - geo(mkt, ks), start=ks[0], end=ks[-1])
        kf = [k for k in ks if share.get(k, {}).get(nm, 0) >= MIN_SHARE]
        if len(kf) >= 240:
            X_ind[nm] = dict(x=geo(s, kf) - geo(mkt, kf), start=kf[0], end=kf[-1], months=len(kf))
    f49 = ff49_map()
    hold_t = {}
    for c in C:
        if not C[c]['us'] or c == 'VOO':     # S&P500 は米国市場そのもの＝e は市場の比重（下で置く）
            continue
        h = holdings_of(c, prof_old, prof_new)
        if c == 'QQQM':
            h = holdings_of('QQQM', prof_old, prof_new) or holdings_of('QQQ', prof_old, prof_new)
        hold_t[c] = h
    sic = sic_lookup({t.upper() for h in hold_t.values() for t, _ in h})

    def ind_of(t):
        s = sic.get(t.upper(), (None,))[0]
        if s is None:
            return None
        k = f49(s)
        return FRENCH_LIKE.get(t.upper(), (k,))[0]
    expo = {}
    for c, h in hold_t.items():
        mapped = [(ind_of(t), w) for t, w in h]
        tot = sum(w for _, w in h)
        mw = sum(w for k, w in mapped if k)
        e = sum(w for k, w in mapped if k in ('Softw', 'Chips')) / mw if mw else None
        xi = sum(w * X_ind[k]['x'] for k, w in mapped if k in X_ind) / mw if mw else None
        xi_raw = sum(w * X_ind_raw[k]['x'] for k, w in mapped if k in X_ind_raw) / mw if mw else None
        top_ind = {}
        for k, w in mapped:
            if k:
                top_ind[k] = top_ind.get(k, 0) + w / mw
        expo[c] = dict(e=e, X_ind=xi, X_ind_raw=xi_raw, coverage=round(mw / tot, 3) if tot else None, n=len(h),
                       top_industries={k: round(v, 3) for k, v in sorted(top_ind.items(), key=lambda kv: -kv[1])[:6]})
    if 'VOO' not in expo or expo['VOO'].get('e') is None:
        expo['VOO'] = dict(e=E_MKT, X_ind=0.0, coverage=None, n=None, top_industries={}, note='米国市場の比重（industry_peak）を使う')

    p2 = M.french_series('6_Portfolios_2x3', want='Average Value Weighted Returns')
    pop = M.french_series('6_Portfolios_ME_OP_2x3', want='Average Value Weighted Returns')
    pdp = M.french_series('Portfolios_Formed_on_D-P', want='Value Weight Returns')
    pme = M.french_series('Portfolios_Formed_on_ME', want='Average Value Weight Returns')
    rsp_p = {}
    dec = ['6-Dec', '7-Dec', '8-Dec', '9-Dec', 'Hi 10']      # French の列名（第6〜第10十分位）
    for k in pme['6-Dec']:
        if all(k in pme[d] for d in dec):
            rsp_p[k] = sum(pme[d][k] for d in dec) / len(dec)

    def x_vs(s, m):
        ks = sorted(k for k in s if k in m)
        return geo(s, ks) - geo(m, ks), ks[0], ks[-1]
    dx = M.french_series('Developed_ex_US_6_Portfolios_ME_BE-ME', want='Average Value Weighted Returns')
    dxf = M.french_tables('Developed_ex_US_3_Factors')
    dxm = {}
    for t, v in dxf.items():
        if v['freq'] == 'monthly':
            ci = [c.lower() for c in v['cols']]
            for d, row in v['data'].items():
                if row[ci.index('mkt-rf')] is not None and row[ci.index('rf')] is not None:
                    dxm[d] = (row[ci.index('mkt-rf')] + row[ci.index('rf')]) / 100
            break
    em = M.french_series('Emerging_Markets_6_Portfolios_ME_BE-ME', want='Average Value Weighted Returns')
    emf = M.french_tables('Emerging_5_Factors')
    emm = {}
    for t, v in emf.items():
        if v['freq'] == 'monthly':
            ci = [c.lower() for c in v['cols']]
            for d, row in v['data'].items():
                if row[ci.index('mkt-rf')] is not None and row[ci.index('rf')] is not None:
                    emm[d] = (row[ci.index('mkt-rf')] + row[ci.index('rf')]) / 100
            break
    style = {
        'VUG': ('BIG LoBM（大型グロース）', *x_vs(p2['BIG LoBM'], mkt)),
        'VTV': ('BIG HiBM（大型バリュー）', *x_vs(p2['BIG HiBM'], mkt)),
        'VBR': ('SMALL HiBM（小型バリュー）', *x_vs(p2['SMALL HiBM'], mkt)),
        'IJR': ('ME 第2五分位', *x_vs(pme['Qnt 2'], mkt)),
        'RSP': ('ME 第6〜10十分位の平均', *x_vs(rsp_p, mkt)),
        'VYM': ('D/P 上位30%', *x_vs(pdp['Hi 30'], mkt)),
        'VIG': ('BIG HiOP（大型×高収益）', *x_vs(pop['BIG HiOP'], mkt)),
        'MOAT': ('BIG HiOP（大型×高収益）', *x_vs(pop['BIG HiOP'], mkt)),
        'PXF': ('先進国（米国除く）BIG HiBM − その市場', *x_vs(dx['BIG HiBM'], dxm)),
        'DEM': ('新興国 BIG HiBM − その市場', *x_vs(em['BIG HiBM'], emm)),
    }
    sector = {'QQQM', 'XLK', 'SMH', 'XLV', 'XLP', 'XLU', 'XLE', 'ITA'}

    def world_b(c, shrink=SHRINK, raw=False):
        if c == 'GLDM':
            return R_GOLD, 0.0, 0.0, '金: 実質1.3%＋インフレ2.5%'
        x, src = 0.0, '地域・市場全体＝上乗せなし'
        if c in style:
            x, src = style[c][1], f'{style[c][0]}（{style[c][2]}〜{style[c][3]}）'
        elif c in sector:
            x = (expo.get(c) or {}).get('X_ind_raw' if raw else 'X_ind') or 0.0
            src = '49業種の長い歴史の上乗せを保有で重み付け' + ('（事前登録どおり・社数の少ない時期を含む）' if raw else f'（業種が時価総額の{100 * MIN_SHARE:g}%以上の月だけ）')
        rec = 0.0
        if C[c]['us']:
            e = (expo.get(c) or {}).get('e')
            if e is None:
                e = E_MKT
            rec = REC_A - REC_B * e
        return R_EQ + shrink * x + rec, x, rec, src

    def jpm_c(c, b, h=H):
        return (H_JPM * JPM[JPM_MAP[c]] / 100 + (h - H_JPM) * b) / h

    def gmo_c(c, b):
        mp = GMO_MAP.get(c)
        if mp is None:
            return jpm_c(c, b)
        real = sum(GMO[k] * w for k, w in mp) / 100
        nom = (1 + real) * (1 + INFL) - 1
        return (H_GMO * nom + (H - H_GMO) * b) / H

    def vg_c(c, b):
        if c in VG_MAP:
            mp = VG_MAP[c]
            if mp is None:
                return jpm_c(c, b)
            v = sum(VG[k] * w for k, w in mp) / 100
        else:
            v = VG['US'] / 100
        return (H_VG * v + (H - H_VG) * b) / H

    # ── 費用・税を引いて4つの世界をそろえる ──
    for c, row in rows.items():
        er_v, dy_v = er_dy(c)
        if er_v is None:
            raise SystemExit(f'{c}: 経費率が取れない（out/etf_forward_profiles.json を確かめる）')
        dy_for_tax = dy_v if dy_v is not None else 0.0
        tax = C[c]['k'] * dy_for_tax
        der = data_er.get(c)
        der = float(der) if der is not None else er_v
        fee_back = der - er_v
        b, x, rec, src = world_b(c)
        cc = jpm_c(c, b)
        row.update(er_vehicle=er_v, dy_vehicle=dy_v, er_data=der, tax_k=C[c]['k'], tax_drag=tax,
                   B_gross=b, B_X=x, B_rec=rec, B_src=src, C_gross=cc,
                   record_share_e=(expo.get(c) or {}).get('e') if C[c]['us'] else None,
                   holdings_coverage=(expo.get(c) or {}).get('coverage') if C[c]['us'] else None,
                   top_industries=(expo.get(c) or {}).get('top_industries') if C[c]['us'] else None)
        row['A1'] = row['A1_gross'] + fee_back - tax
        row['A2'] = row['A2_gross'] + fee_back - tax
        row['B'] = b - er_v - tax
        row['C'] = cc - er_v - tax
        # 感度用
        row['_b03'] = world_b(c, 0.3)[0] - er_v - tax
        row['_b07'] = world_b(c, 0.7)[0] - er_v - tax
        row['_c03'] = jpm_c(c, world_b(c, 0.3)[0]) - er_v - tax
        row['_c07'] = jpm_c(c, world_b(c, 0.7)[0]) - er_v - tax
        row['_c_gmo'] = gmo_c(c, b) - er_v - tax
        row['_c_vg'] = vg_c(c, b) - er_v - tax
        row['_c_h30'] = jpm_c(c, b, 30) - er_v - tax
        braw = world_b(c, raw=True)[0]
        row['_b_raw'] = braw - er_v - tax
        row['_c_raw'] = jpm_c(c, braw) - er_v - tax
        row['B_X_raw'] = world_b(c, raw=True)[1]
        row['_notax'] = tax

    W = ['A1', 'A2', 'B', 'C']

    def rank_by(key_fn, names=None):
        names = names or list(rows)
        srt = sorted(names, key=lambda c: (-key_fn(c)[0], -key_fn(c)[1]))
        return srt

    def score(c, worlds):
        v = [rows[c][w] for w in worlds]
        return S.mean(v), min(v)
    order = rank_by(lambda c: score(c, W))
    wr = {w: {c: i + 1 for i, c in enumerate(sorted(rows, key=lambda c: -rows[c][w]))} for w in W}
    for i, c in enumerate(order):
        rows[c]['rank'] = i + 1
        rows[c]['score'] = score(c, W)[0]
        rows[c]['worst'] = score(c, W)[1]
        rows[c]['worst_world'] = min(W, key=lambda w: rows[c][w])
        rows[c]['best_world'] = max(W, key=lambda w: rows[c][w])
        rows[c]['world_rank'] = {w: wr[w][c] for w in W}
        rows[c]['top10_in_worlds'] = sum(1 for w in W if wr[w][c] <= 10)

    def top10(worlds_vals):
        """worlds_vals: {候補: [値…]} → 平均の順位の上位10"""
        srt = sorted(worlds_vals, key=lambda c: (-S.mean(worlds_vals[c]), -min(worlds_vals[c])))
        return srt[:10]
    sens = {}
    sens['S0_事前登録どおり（業種の時価総額の下限なし）'] = top10({c: [rows[c]['A1'], rows[c]['A2'], rows[c]['_b_raw'], rows[c]['_c_raw']] for c in rows})
    sens['S1_順位の平均'] = sorted(rows, key=lambda c: (S.mean(wr[w][c] for w in W), -rows[c]['worst']))[:10]
    sens['S2_A2を外す'] = top10({c: [rows[c][w] for w in ('A1', 'B', 'C')] for c in rows})
    sens['S3_縮み0.3'] = top10({c: [rows[c]['A1'], rows[c]['A2'], rows[c]['_b03'], rows[c]['_c03']] for c in rows})
    sens['S3_縮み0.7'] = top10({c: [rows[c]['A1'], rows[c]['A2'], rows[c]['_b07'], rows[c]['_c07']] for c in rows})
    sens['S4_CをGMOに'] = top10({c: [rows[c]['A1'], rows[c]['A2'], rows[c]['B'], rows[c]['_c_gmo']] for c in rows})
    sens['S4_CをVanguardに'] = top10({c: [rows[c]['A1'], rows[c]['A2'], rows[c]['B'], rows[c]['_c_vg']] for c in rows})
    sens['S5_期間30年'] = top10({c: [rows[c]['A1'], rows[c]['A2'], rows[c]['B'], rows[c]['_c_h30']] for c in rows})
    sens['S6_外国税なし'] = top10({c: [rows[c][w] + rows[c]['_notax'] for w in W] for c in rows})
    main_top = order[:10]
    stability = {c: sum(1 for v in sens.values() if c in v) for c in rows}

    def pct(x, d=2):
        return None if x is None else round(100 * x, d)
    table = []
    for c in order:
        r = rows[c]
        table.append({
            'rank': r['rank'], 't': c, 'ja': r['ja'], 'vehicle': r['vehicle'],
            '平均(%/年)': pct(r['score']), '最悪の世界(%/年)': pct(r['worst']), '最悪の世界': r['worst_world'], '最良の世界': r['best_world'],
            'A1(%/年)': pct(r['A1']), 'A2(%/年)': pct(r['A2']), 'B(%/年)': pct(r['B']), 'C(%/年)': pct(r['C']),
            '各世界の順位': r['world_rank'], '上位10に入った世界の数': r['top10_in_worlds'],
            '感度9本のうち上位10に残った数': stability[c],
            '経費率(%)': pct(r['er_vehicle'], 3), '配当利回り(%)': pct(r['dy_vehicle']), '外国税の目減り(%/年)': pct(r['tax_drag'], 3),
            'A1_ぶれ(%/年)': pct(r['vol_A1'], 1), 'A1_最大下落(%)': pct(r['maxdd_A1'], 1),
            'A2_ぶれ(%/年)': pct(r['vol_A2'], 1), 'A2_最大下落(%)': pct(r['maxdd_A2'], 1),
            'B_上乗せX(%/年・縮める前)': pct(r['B_X']), 'B_上乗せX_事前登録どおり(%/年)': pct(r.get('B_X_raw')), 'B_記録の業種REC(%/年)': pct(r['B_rec'], 3), 'B_上乗せの出どころ': r['B_src'],
            '記録の二業種の比率e': None if r['record_share_e'] is None else round(r['record_share_e'], 3),
            '中身の読めた割合': r['holdings_coverage'], '業種の上位': r['top_industries'],
            'データ': f"{r['data']}" + (f"＋〜{r['proxy_until']}は{r['proxy']}" if r['proxy'] else ''),
            'A1の注': r['A1_note'],
        })
    doc = {
        'generated': datetime.date.today().isoformat(), 'tool': 'night/etf_forward_rank.py', 'prereg': PREREG,
        'question': 'これからの最強のETF（楽天で買える25本）を4つの世界の今後の年率で並べる',
        'unit': 'ドル建ての幾何年率（費用と NISA で取り戻せない配当の外国税を引いた後）。円でもドル円の動きは全候補に同じだけ掛かるので順位は同じ',
        'worlds': {'A1': f'{A1[0]}→{A1[1]} の実績（直近26年）', 'A2': f'{A2[0]}→{A2[1]} の実績（直近15年）',
                   'B': f'100年の平均: R株 {100 * R_EQ:.2f}%＋{SHRINK}×X＋REC／金 {100 * R_GOLD:.2f}%',
                   'C': f'JPM 2026 LTCMA を {H_JPM}年・その後 B（{H}年）'},
        'top10': [{'rank': i + 1, 't': c, 'ja': rows[c]['ja'], 'vehicle': rows[c]['vehicle'], '平均(%/年)': pct(rows[c]['score']),
                   '最悪の世界(%/年)': pct(rows[c]['worst'])} for i, c in enumerate(main_top)],
        'table': table,
        'sensitivity_top10': sens,
        'splice_checks': checks,
        'B_industry_long_run_excess(%/年・縮める前)': {k: dict(x=pct(v['x']), start=v['start'], end=v['end'], months=v['months'],
                                                         x_事前登録どおり=pct(X_ind_raw[k]['x']) if k in X_ind_raw else None)
                                                    for k, v in sorted(X_ind.items(), key=lambda kv: -kv[1]['x'])},
        'B_industry_min_share': f'業種の長い歴史は、その業種が米国株の時価総額の{100 * MIN_SHARE:g}%以上ある月だけで測った（結果を見た後の是正・事前登録の外。S0 が事前登録どおり）',
        'B_style_long_run_excess(%/年・縮める前)': {c: dict(portfolio=v[0], x=pct(v[1]), start=v[2], end=v[3]) for c, v in style.items()},
        'SPY_A1(%/年)': pct(spy_a1),
        'inputs': {'R株': pct(R_EQ), 'R金': pct(R_GOLD), '縮み': SHRINK, 'REC': '0.204%−0.52%×e', 'e_米国市場': E_MKT,
                   'JPM': JPM, 'GMO_実質の中点': GMO, 'Vanguard': VG, 'H': H, 'H_JPM': H_JPM},
        '⚠': [
            '4つの世界は仮定で、重みは同じと置いた。どれが来るかは分からない',
            'A1・A2 は一つの道筋（運を含む）。代理（VTSMX/VGTSX・VIGRX・VIVAX・VISVX・VTMGX・VEIEX・FSDAX・DFIVX・DFEVX・金先物・French の BIG HiOP）はETFそのものではない',
            'B の業種・型の上乗せは米国の歴史（French・CRSP）。国・地域を同じと置くのは仮定',
            'C は JPM 一社。業種の予想は無いので米国の業種は米国大型と同じ数字',
            'ランキングは『1本だけ持つなら』の比べっこ。組み合わせ（分散）の効果は別',
            '判定・配分には使わない（材料）',
        ],
    }
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print(f'→ {OUT}')
    print(f"{'順':>2} {'候補':6} {'名前':16} {'平均':>6} {'最悪':>6} {'A1':>6} {'A2':>6} {'B':>6} {'C':>6}  各世界の順位   上位10の数 感度")
    for t in table:
        wrk = t['各世界の順位']
        print(f"{t['rank']:2d} {t['t']:6} {t['ja'][:14]:16} {t['平均(%/年)']:6.2f} {t['最悪の世界(%/年)']:6.2f} {t['A1(%/年)']:6.2f} {t['A2(%/年)']:6.2f} {t['B(%/年)']:6.2f} {t['C(%/年)']:6.2f}  "
              f"{wrk['A1']:2d}/{wrk['A2']:2d}/{wrk['B']:2d}/{wrk['C']:2d}   {t['上位10に入った世界の数']}   {t['感度9本のうち上位10に残った数']}")
    print('感度の上位10:')
    for k, v in sens.items():
        print(f'  {k}: {" ".join(v)}')
    print('つなぎ目:', {k: (v['corr'], v['overlap_months']) for k, v in checks.items()})


if __name__ == '__main__':
    main()
