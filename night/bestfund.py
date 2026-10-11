#!/usr/bin/env python3
"""night/bestfund.py — 最高の投資信託・ETF を歴史検証と未来検証で探す（bestfund・読むだけ・門・配分には触れない）

2026-10-11 ユーザー「時間を使って最高の投資信託かETFを探して。歴史検証そして未来検証全てやって最も良いとあなたが判断するものが何か調べ抜いて。」
事前登録 out/bestfund_prereg.json（d5eab7f・測る前に固定）どおりに計算する。材料は night/bestfund_data.py（つなぎ・器・費用）と
night/bestfund_persist.py（H4 の λ）、機関の予想 out/bestfund_cma.json（世界 C）、今の割高さ out/bestfund_valuations.json（世界 D）。

  H1 円で毎月同額の積立の転がる窓（20・15・10年・1か月ずつ）: 内部収益率の中央・10%点・最小、全世界株と S&P500 に勝った窓の割合
     （長いつなぎ 1950〜／A1 窓 2000-09〜／実物と指数だけ の3通り。費用を引いた後）
  H2 円建ての一括の転がる20年の年率・最大下落・水没期間  H3 時代別の年率と全世界株（無い時代は S&P500）との差
  世界 A1・A2・B・C・D・E の今後20年の年率（米国・世界はドル建て・日本は円建て。費用と取り戻せない外国税を引いた後）
  模擬: 各賭け×各世界 20,000本の240か月（円・ドル円の期待の変化は0）。確実性等価（γ=2）を主の物差しに、感度19本で順位の堅さを見る

  python3 night/bestfund.py            → out/bestfund.json
"""
import datetime, json, math, os, statistics as S, sys, hashlib

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import bestfund_data as D      # noqa: E402

OUT = os.path.join(BASE, 'out', 'bestfund.json')
PREREG = 'out/bestfund_prereg.json（d5eab7f）'
CMA = os.path.join(BASE, 'out', 'bestfund_cma.json')
VAL = os.path.join(BASE, 'out', 'bestfund_valuations.json')
PERSIST = os.path.join(BASE, 'out', 'bestfund_persist.json')
BETS = list(D.CHAINS)
WORLDS = ['A1', 'A2', 'B', 'C', 'D', 'E']
N_PATHS, N_M = 20000, 240
SEED = 20261011
GAMMA = 2
REF_COST = {'SOFT': 0.0038 + D.FX_FEE, 'MOM': 0.0015 + D.FX_FEE, 'LOWVOL': 0.0015 + D.FX_FEE, 'REIT': 0.0013 + D.FX_FEE}
B_BOND = 0.045
# etf_forward_rank の候補 → この調査の賭け（世界 B は同じ式の値をそのまま使う）
FWD_MAP = {'ACWI': 'VT', 'SP500': 'VOO', 'DEVXUS': 'VEA', 'EM': 'VWO', 'TOPIX': 'TOPIX', 'INDIA': 'EPI', 'NDX': 'QQQM', 'GROWTH': 'VUG',
           'TECH_SPDR': 'XLK', 'SEMI_MV': 'SMH', 'HEALTH': 'XLV', 'STAPLES': 'XLP', 'UTIL': 'XLU', 'ENERGY': 'XLE', 'DEFENSE': 'ITA',
           'VALUE': 'VTV', 'SMALLV': 'VBR', 'SMALL': 'IJR', 'DIVG': 'VIG', 'HIDIV': 'VYM', 'QUALITY': 'MOAT', 'EQW': 'RSP',
           'DXUS_VAL': 'PXF', 'EM_VAL': 'DEM', 'GOLD': 'GLDM'}
HOLD_MAP = {'SEMI_SOX': 'SOXX', 'SOFT': 'IGV', 'INET': 'FDN', 'MEGAG': 'MGK', 'FIN': 'XLF', 'FANG': 'FANG', 'TECH_VGT': 'VGT'}


def months(a, b):
    out, y, m = [], a // 100, a % 100
    while y * 100 + m <= b:
        out.append(y * 100 + m)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def geo(r, ks):
    if not ks or any(k not in r for k in ks):
        return None
    return math.exp(math.fsum(math.log1p(r[k]) for k in ks) * 12 / len(ks)) - 1


def pct(x, d=2):
    return None if x is None else round(100 * x, d)


# ───────────────────────── 費用 ─────────────────────────
def costs(user_vehicle=False):
    out = {}
    for b in BETS:
        v = D.VEH[b]
        tax = v['k'] * v['dy']
        c = D.cost_of(b, 'best')
        tot = c['total'] if c else REF_COST[b] + tax
        if user_vehicle and b == 'NDX':
            tot = 0.00495 + tax          # 感度: ユーザーの今の器（iFreeNEXT NASDAQ100）
        out[b] = tot
    return out


def nat(ch, b):
    return ch[b]['jpy'] if b in D.JPY_NATIVE else ch[b]['usd']


# ───────────────────────── 歴史の世界 A1・A2 ─────────────────────────
def world_hist(ch, cost, win):
    spx = ch['SP500']['usd']
    ks = months(*win)
    out, notes = {}, {}
    for b in BETS:
        r = nat(ch, b)
        if all(k in r for k in ks):
            g = geo(r, ks)
        else:
            own = sorted(k for k in r if win[0] <= k <= win[1])
            g = geo(spx, ks) + geo(r, own) - geo(spx, own)
            notes[b] = f'{own[0]}〜{own[-1]}（{len(own) / 12:.1f}年）の S&P500 との差 {100 * (geo(r, own) - geo(spx, own)):+.2f}%/年 を S&P500 に足した'
        out[b] = g - cost[b]
    return out, notes


# ───────────────────────── 世界 B ─────────────────────────
def world_b_gross():
    """→ {賭け: (B の総額〔費用前〕, 上乗せ X, REC, 出どころ)}"""
    import etf_forward_rank as F
    from industry_exposure import sic_lookup, FRENCH_LIKE
    from industry_trends import ff49_map
    res = F.main(write=False)
    rows, doc = res['rows'], res['doc']
    xind = {k: v['x'] / 100 for k, v in doc['B_industry_long_run_excess(%/年・縮める前)'].items()}
    out = {}
    for b, c in FWD_MAP.items():
        r = rows[c]
        out[b] = (r['B_gross'], r['B_X'], r['B_rec'], f"etf_forward_rank の {c} と同じ値（{r['B_src']}）")
    hold = json.load(open(os.path.join(BASE, 'out', 'bestfund_holdings.json')))
    prof_old = json.load(open(os.path.join(BASE, 'out', 'etf_profiles.json')))['etfs']
    H = {b: (hold[t] if t in hold else [(h[0], h[1]) for h in prof_old[t]['h']]) for b, t in HOLD_MAP.items()}
    sic = sic_lookup({t.upper() for h in H.values() for t, _ in h})
    f49 = ff49_map()

    def ind_of(t):
        s = sic.get(t.upper(), (None,))[0]
        if s is None:
            return None
        k = f49(s)
        return FRENCH_LIKE.get(t.upper(), (k,))[0]
    for b, h in H.items():
        mapped = [(ind_of(t), w) for t, w in h]
        mw = sum(w for k, w in mapped if k)
        tot = sum(w for _, w in h)
        e = sum(w for k, w in mapped if k in ('Softw', 'Chips')) / mw
        x = sum(w * xind[k] for k, w in mapped if k in xind) / mw
        rec = F.REC_A - F.REC_B * e
        top = {}
        for k, w in mapped:
            if k:
                top[k] = top.get(k, 0) + w / mw
        out[b] = (F.R_EQ + F.SHRINK * x + rec, x, rec,
                  f'{HOLD_MAP[b]} の上位の保有（読めた割合 {mw / tot:.0%}）の業種で重み付け・e={e:.2f}・業種 '
                  + ' '.join(f'{k}{v:.0%}' for k, v in sorted(top.items(), key=lambda kv: -kv[1])[:4]))
    import mw_common as M
    mkt = M.ff_factors()['mkt']
    for b, (ds, col, want) in {'MOM': ('6_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 'Average Value Weighted Returns'),
                               'LOWVOL': ('Portfolios_Formed_on_VAR', 'Lo 20', 'Value Weighted Returns')}.items():
        s = M.french_series(ds, want=want)[col]
        ks = sorted(k for k in s if k in mkt)
        x = geo(s, ks) - geo(mkt, ks)
        rec = F.REC_A - F.REC_B * F.E_MKT
        out[b] = (F.R_EQ + F.SHRINK * x + rec, x, rec, f'French {col}（{ks[0]}〜{ks[-1]}）の市場との差・e は市場の比重（保有を写していない）')
    for b in ('USTOT',):
        rec = F.REC_A - F.REC_B * F.E_MKT
        out[b] = (F.R_EQ + rec, 0.0, rec, '米国市場全体＝上乗せなし・e は市場の比重')
    for b in ('KOKUSAI', 'N225'):
        out[b] = (F.R_EQ, 0.0, 0.0, '地域・市場全体＝上乗せなし（米国外を含む＝REC なし・etf_forward_rank の VT・TOPIX と同じ扱い）')
    out['REIT'] = (F.R_EQ, 0.0, 0.0, '保有を写していない＝上乗せ0と置いた（楽天で持てる器が無く最終候補の外）')
    out['BOND'] = (B_BOND, 0.0, 0.0, '米国総合債券の長期の名目 4.5%（事前登録）')
    return out, {'R_EQ': F.R_EQ, 'R_GOLD': F.R_GOLD, 'SHRINK': F.SHRINK, 'REC': f'{F.REC_A}−{F.REC_B}×e', 'E_MKT': F.E_MKT}


# ───────────────────────── 世界 C（機関の予想） ─────────────────────────
def world_c_gross(bgross, cma=None):
    """→ {賭け: (C の総額, 機関の平均〔10年〕, 機関の数, 内訳)}。機関の数字は night/bestfund_cma.py がそろえた out/bestfund_cma.json
    （名目・幾何・米国と世界はドル・日本は円）。C＝(10×機関の平均＋10×B)/20（事前登録）"""
    if cma is None:
        if not os.path.exists(CMA):
            return None
        cma = json.load(open(CMA))
    out = {}
    for b in BETS:
        e = cma['bets'].get(b) or {}
        if not e.get('avg_pct'):
            out[b] = (bgross[b][0], None, 0, '機関の予想を当てられなかった＝B と同じ')
            continue
        avg = e['avg_pct'] / 100
        out[b] = ((10 * avg + 10 * bgross[b][0]) / 20, avg, e['n'], [(v['institution'], v['class'], v['value_pct']) for v in e['values']])
    return out


# ───────────────────────── 世界 D（今の割高さ） ─────────────────────────
def g20_of(gc, gl):
    gc = min(gc, 0.25)
    path = [gc] * 5 + [gc + (gl - gc) * (i / 5) for i in range(1, 6)] + [gl] * 10
    return math.exp(sum(math.log1p(g) for g in path) / 20) - 1


G_L = {'US': 0.05, 'GLOBAL': 0.05, 'DEV': 0.05, 'EM': 0.06, 'INDIA': 0.06, 'JAPAN': 0.035}   # 事前登録 future_worlds.D.g20
D_REGION = {'ACWI': 'GLOBAL', 'KOKUSAI': 'DEV', 'DEVXUS': 'DEV', 'DXUS_VAL': 'DEV', 'EM': 'EM', 'EM_VAL': 'EM', 'INDIA': 'INDIA',
            'TOPIX': 'JAPAN', 'N225': 'JAPAN'}


def world_d_gross(cgross, val=None, alpha=0.5):
    """→ {賭け: (D の総額, 内訳 dict or 'C と同じ')}。alpha は割高さの戻りの割合（主 0.5・感度 0 と 1）。
    入力（今の PER・同じ物差しの PER の長期の中央値・配当利回り・アナリストの長期の伸びの予想 g_c）は out/bestfund_valuations.json"""
    if val is None:
        if not os.path.exists(VAL):
            return None
        val = json.load(open(VAL))
    out = {}
    for b in BETS:
        v = (val.get('bets') or {}).get(b)
        need = ('pe_now', 'pe_median', 'dy', 'g_c')
        if b in ('GOLD', 'BOND') or not v or any(v.get(k) in (None, '') for k in need):
            out[b] = (cgross[b][0], 'C と同じ（入力が欠けた）' if b not in ('GOLD', 'BOND') else 'C と同じ（PER の無い資産）')
            continue
        gl = G_L[D_REGION.get(b, 'US')]
        g = g20_of(v['g_c'], gl)
        pe_t = v['pe_now'] * (v['pe_median'] / v['pe_now']) ** alpha
        dv = math.log(pe_t / v['pe_now']) / 20
        out[b] = (v['dy'] + g + dv, dict(dy=v['dy'], g_c=v['g_c'], g20=round(g, 4), pe_now=v['pe_now'], pe_median=v['pe_median'],
                                        dv=round(dv, 4), g_L=gl, src=v.get('src')))
    return out


# ───────────────────────── 世界 E ─────────────────────────
def world_e(ch, cost, bnet, cnet, dnet, lam):
    out, detail = {}, {}
    for b in BETS:
        reg = D.region_of(b)
        m = S.mean([bnet[reg], cnet[reg], dnet[reg]])
        if b == reg:
            x = 0.0
            win = None
        else:
            r, q = nat(ch, b), nat(ch, reg)
            ks = sorted(k for k in r if k in q)
            x = (geo(r, ks) - geo(q, ks)) - (cost[b] - cost[reg])
            win = f'{ks[0]}〜{ks[-1]}'
        out[b] = m + lam * x
        detail[b] = dict(region=reg, M=round(m, 5), X=round(x, 5), window=win)
    return out, detail


# ───────────────────────── ぶれと形 ─────────────────────────
def sigma_z(ch):
    """→ {賭け: (σ 年率, z の配列, 窓)}。σ は A1 窓の円建ての月次の対数リターンの年率の標準偏差（短い賭けは S&P500 の比で直す）"""
    ks = months(*D.A1)
    spx = ch['SP500']['jpy']
    lx = np.array([math.log1p(spx[k]) for k in ks])
    s_spx = lx.std(ddof=1) * math.sqrt(12)
    out = {}
    for b in BETS:
        r = ch[b]['jpy']
        own = [k for k in ks if k in r]
        x = np.array([math.log1p(r[k]) for k in own])
        s_own = x.std(ddof=1) * math.sqrt(12)
        if len(own) == len(ks):
            s = s_own
        else:
            ls = np.array([math.log1p(spx[k]) for k in own])
            s = s_own * s_spx / (ls.std(ddof=1) * math.sqrt(12))
        z = (x - x.mean()) / x.std(ddof=1)
        out[b] = (s, z, f'{own[0]}〜{own[-1]}')
    return out


# ───────────────────────── 積立の倍率と年率 ─────────────────────────
def irr_from_multiple(m, n=N_M):
    """毎月1を n か月入れた最終額 ÷ n ＝ m のときの年率（配列可）。二分法"""
    m = np.atleast_1d(np.asarray(m, dtype=float))
    lo, hi = np.full(m.shape, -0.06), np.full(m.shape, 0.06)

    def f(q):
        q = np.where(np.abs(q) < 1e-12, 1e-12, q)
        return (np.power(1 + q, n + 1) - (1 + q)) / q / n
    for _ in range(80):
        mid = (lo + hi) / 2
        big = f(mid) > m
        hi = np.where(big, mid, hi)
        lo = np.where(big, lo, mid)
    q = (lo + hi) / 2
    return np.power(1 + q, 12) - 1


def multiple_for_irr(a, n=N_M):
    q = (1 + a) ** (1 / 12) - 1
    return ((1 + q) ** (n + 1) - (1 + q)) / q / n


def dca_multiple(logret):
    """logret: (本数, 月数) → 最終額 ÷ 投下額"""
    w = np.zeros(logret.shape[0])
    for t in range(logret.shape[1]):
        w = (w + 1.0) * np.exp(logret[:, t])
    return w / logret.shape[1]


def ce(mult, gamma):
    mult = np.asarray(mult)
    if gamma == 1:
        return float(np.exp(np.mean(np.log(mult))))
    return float(np.mean(np.power(mult, 1 - gamma)) ** (1 / (1 - gamma)))


# ───────────────────────── 歴史の検定 H1〜H3 ─────────────────────────
def window_multiples(r, years, start=None, end=D.END):
    """{yyyymm: r} の毎月同額の積立の転がる窓（1か月ずつ）→ {起点: 倍率}"""
    ks = sorted(k for k in r if (start is None or k >= start) and k <= end)
    # 続いている部分だけ
    n = years * 12
    out = {}
    if len(ks) < n:
        return out
    arr = np.array([r[k] for k in ks])
    lg = np.log1p(arr)
    cum = np.concatenate([[0.0], np.cumsum(lg)])          # cum[i] = sum lg[:i]
    inv = np.exp(-cum[:-1])                                # 1/C_{j-1}（j=0..N-1）
    pre = np.concatenate([[0.0], np.cumsum(inv)])
    for s in range(0, len(ks) - n + 1):
        e = s + n
        if (ks[e - 1] // 100 * 12 + ks[e - 1] % 100) - (ks[s] // 100 * 12 + ks[s] % 100) != n - 1:
            continue
        v = math.exp(cum[e]) * (pre[e] - pre[s])
        out[ks[s]] = v / n
    return out


def h1(ch, cost):
    res = {}
    ref = {}
    for b in BETS:
        net = {k: v - cost[b] / 12 for k, v in ch[b]['jpy'].items()}
        ref[b] = net
    periods = {'長いつなぎ（1950〜）': 195001, 'A1 窓（2000-09〜）': 200009}
    for b in BETS:
        e = {}
        for pname, st in list(periods.items()) + [('実物と指数だけ', ch[b]['first_real'])]:
            pe = {}
            for yrs in (20, 15, 10):
                wm = window_multiples(ref[b], yrs, start=st)
                if not wm:
                    continue
                irr = irr_from_multiple(np.array(list(wm.values())), yrs * 12)
                row = {'windows': len(wm), 'median': pct(float(np.median(irr))), 'p10': pct(float(np.percentile(irr, 10))),
                       'min': pct(float(irr.min())), 'from': min(wm), 'to': max(wm)}
                for cmp_ in ('ACWI', 'SP500'):
                    if b == cmp_:
                        continue
                    wc = window_multiples(ref[cmp_], yrs, start=st if pname != '実物と指数だけ' else ch[b]['first_real'])
                    common = [k for k in wm if k in wc]
                    if common:
                        row[f'beat_{cmp_}'] = round(sum(1 for k in common if wm[k] > wc[k]) / len(common), 3)
                        row[f'beat_{cmp_}_n'] = len(common)
                pe[f'{yrs}y'] = row
            if pe:
                e[pname] = pe
        res[b] = e
    return res


def h2(ch, cost):
    res = {}
    for b in BETS:
        r = {k: v - cost[b] / 12 for k, v in ch[b]['jpy'].items() if k >= 195001}
        ks = sorted(r)
        if len(ks) < 240:
            res[b] = None
            continue
        lv, pk, dd, uw, uw_max, uw_start = 1.0, 1.0, 0.0, 0, 0, None
        for k in ks:
            lv *= 1 + r[k]
            if lv >= pk:
                pk = lv
                uw = 0
            else:
                uw += 1
                uw_max = max(uw_max, uw)
            dd = min(dd, lv / pk - 1)
        rolls = []
        for i in range(0, len(ks) - 240 + 1):
            w = ks[i:i + 240]
            rolls.append(geo(r, w))
        res[b] = {'from': ks[0], 'lump20_median': pct(S.median(rolls)), 'lump20_min': pct(min(rolls)),
                  'lump20_windows': len(rolls), 'max_drawdown': pct(dd, 1), 'longest_underwater_years': round(uw_max / 12, 1)}
    return res


def h3(ch, cost):
    eras = {'1950〜1974': (195001, 197412), '1975〜1999': (197501, 199912), '2000〜2026-09': (200001, 202609)}
    res = {}
    for b in BETS:
        r = {k: v - cost[b] / 12 for k, v in ch[b]['jpy'].items()}
        e = {}
        for nm, (a, z) in eras.items():
            ks = months(a, z)
            g = geo(r, ks)
            if g is None:
                continue
            ac = {k: v - cost['ACWI'] / 12 for k, v in ch['ACWI']['jpy'].items()}
            sp = {k: v - cost['SP500'] / 12 for k, v in ch['SP500']['jpy'].items()}
            ga = geo(ac, ks)
            ref, gref = ('ACWI', ga) if ga is not None else ('SP500', geo(sp, ks))
            e[nm] = {'annual': pct(g), 'vs': ref, 'diff': pct(g - gref)}
        res[b] = e
    return res


# ───────────────────────── 模擬 ─────────────────────────
def simulate(mu, sz, worlds, sigma_mult=1.0, normal=False, fx_shift=0.0, seed_tag=''):
    """mu: {世界: {賭け: 年率}} → {賭け: {世界: 倍率の配列}}。
    感度は同じ乱数（seed_tag が同じ）で回す＝入力を変えた分だけが順位に出る（共通乱数）。正規分布の感度だけ別の乱数"""
    out = {}
    for b in BETS:
        s, z, _ = sz[b]
        h = int(hashlib.sha256(f'{SEED}:{b}:{seed_tag}'.encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(h)
        out[b] = {}
        for wi, w in enumerate(worlds):
            if normal:
                zz = rng.standard_normal((N_PATHS, N_M))
            else:
                zz = z[rng.integers(0, len(z), size=(N_PATHS, N_M))]
            m = mu[w][b] if b in D.JPY_NATIVE else (1 + mu[w][b]) * (1 + fx_shift) - 1
            lr = math.log1p(m) / 12 + (s * sigma_mult) / math.sqrt(12) * zz
            out[b][w] = dca_multiple(lr)
    return out


def summarize_bet(mults, worlds, gamma=GAMMA):
    pool = np.concatenate([mults[w] for w in worlds])
    c = ce(pool, gamma)
    irr = irr_from_multiple(np.array([c]))[0]
    m10, m15 = multiple_for_irr(0.10), multiple_for_irr(0.15)
    return {'ce_multiple': round(c, 4), 'ce_irr': irr, 'median_irr': float(irr_from_multiple(np.array([np.median(pool)]))[0]),
            'p_ge10': float(np.mean(pool >= m10)), 'p_ge15': float(np.mean(pool >= m15)), 'p_loss': float(np.mean(pool < 1.0)),
            'p5_irr': float(irr_from_multiple(np.array([np.percentile(pool, 5)]))[0])}


def rank_ce(sims, worlds, gamma, pool_bets):
    sc = {b: summarize_bet(sims[b], worlds, gamma)['ce_irr'] for b in pool_bets}
    return sorted(pool_bets, key=lambda b: -sc[b]), sc


def worlds_all(ch, cost, bg, cg, dg, lam):
    a1, a1n = world_hist(ch, cost, D.A1)
    a2, a2n = world_hist(ch, cost, D.A2)
    bnet = {b: bg[b][0] - cost[b] for b in BETS}
    cnet = {b: cg[b][0] - cost[b] for b in BETS}
    dnet = {b: dg[b][0] - cost[b] for b in BETS}
    e, edet = world_e(ch, cost, bnet, cnet, dnet, lam)
    return {'A1': a1, 'A2': a2, 'B': bnet, 'C': cnet, 'D': dnet, 'E': e}, {'A1': a1n, 'A2': a2n, 'E': edet}


# ───────────────────────── 参考: 今の ETF 側の配合（事前登録の外・判定には使わない） ─────────────────────────
REF_MIX = {'NDX': 50, 'SEMI_MV': 20, 'DEFENSE': 15}     # portfolio.json の ETF 側（NASDAQ100 50・SMH 20・その他15＝ITA）を正規化


def ref_mix(ch, cost, mu):
    """今の ETF 側を毎月組み直した混合の各世界の年率・σ・z（世界 B〜E は重みつき平均＋分散の上乗せ ½(Σwσ²−w'Σw)＝etf_forward_combo と同じ）"""
    tot = sum(REF_MIX.values())
    w = {b: v / tot for b, v in REF_MIX.items()}
    ks = sorted(set.intersection(*[set(ch[b]['usd']) for b in w]))
    mix_usd = {k: sum(w[b] * ch[b]['usd'][k] for b in w) for k in ks}
    mix_jpy = D.to_jpy(mix_usd)
    c = sum(w[b] * cost[b] for b in w)
    a1 = geo(mix_usd, months(*D.A1)) - c
    a2 = geo(mix_usd, months(*D.A2)) - c
    k1 = months(*D.A1)
    X = np.array([[math.log1p(ch[b]['usd'][k]) for k in k1] for b in w])
    cov = np.cov(X) * 12
    wv = np.array([w[b] for b in w])
    div = 0.5 * (float(np.sum(wv * np.diag(cov))) - float(wv @ cov @ wv))
    out = {'A1': a1, 'A2': a2}
    for wd in ('B', 'C', 'D', 'E'):
        out[wd] = sum(w[b] * mu[wd][b] for b in w) + div
    lx = np.array([math.log1p(mix_jpy[k]) for k in k1])
    s = lx.std(ddof=1) * math.sqrt(12)
    z = (lx - lx.mean()) / lx.std(ddof=1)
    return out, (s, z, f'{k1[0]}〜{k1[-1]}'), {'weights': {b: round(v, 3) for b, v in w.items()}, 'cost': c, 'diversification_bonus': div}


def main():
    ch = D.chains()
    cost = costs()
    elig = [b for b in BETS if D.eligible(b)]
    tsumi = [b for b in elig if D.cost_of(b, 'tsumitate')]
    bg, b_inputs = world_b_gross()
    cg = world_c_gross(bg)
    c_note = None
    if cg is None:
        cg = {b: (bg[b][0], None, 0, '暫定: 機関の予想の材料がまだ無い＝B と同じ') for b in BETS}
        c_note = '⚠ 暫定（out/bestfund_cma.json が無い）'
    dg = world_d_gross(cg)
    d_note = None
    if dg is None:
        dg = {b: (cg[b][0], '暫定: 割高さの材料がまだ無い＝C と同じ') for b in BETS}
        d_note = '⚠ 暫定（out/bestfund_valuations.json が無い）'
    per = json.load(open(PERSIST))
    lam = per['lambda_main']['lambda']
    lam10 = per['lambda_L10_H10']['lambda']
    mu, wnotes = worlds_all(ch, cost, bg, cg, dg, lam)
    a1n, a2n, edet = wnotes['A1'], wnotes['A2'], wnotes['E']
    bnet, cnet, dnet = mu['B'], mu['C'], mu['D']
    sz = sigma_z(ch)

    # ── 主の模擬 ──
    sims = simulate(mu, sz, WORLDS)
    summ = {b: summarize_bet(sims[b], WORLDS) for b in BETS}
    order = sorted(elig, key=lambda b: -summ[b]['ce_irr'])
    best = {w: max(mu[w][b] for b in elig) for w in WORLDS}
    regret = {b: max(best[w] - mu[w][b] for w in WORLDS) for b in BETS}

    # ── 参考: 今の ETF 側の配合（判定・順位には使わない） ──
    rm_mu, rm_sz, rm_info = ref_mix(ch, cost, mu)
    mu_r = {w: {'MIX': rm_mu[w]} for w in WORLDS}
    rng = np.random.default_rng(int(hashlib.sha256(f'{SEED}:MIX:'.encode()).hexdigest()[:8], 16))
    rm_sims = {}
    for w in WORLDS:
        zz = rm_sz[1][rng.integers(0, len(rm_sz[1]), size=(N_PATHS, N_M))]
        rm_sims[w] = dca_multiple(math.log1p(rm_mu[w]) / 12 + rm_sz[0] / math.sqrt(12) * zz)
    rm_sum = summarize_bet(rm_sims, WORLDS)
    reference_mix = {'what': '今の ETF 側（NASDAQ100 50・SMH 20・ITA 15 を正規化・毎月の組み直し）＝参考（事前登録の外・判定に使わない）',
                     **rm_info, 'worlds_pct': {w: pct(rm_mu[w]) for w in WORLDS}, 'sigma_pct': pct(rm_sz[0], 1),
                     'CE_γ2': pct(rm_sum['ce_irr']), 'CE_γ1': pct(irr_from_multiple(np.array([ce(np.concatenate([rm_sims[w] for w in WORLDS]), 1)]))[0]),
                     'CE_γ5': pct(irr_from_multiple(np.array([ce(np.concatenate([rm_sims[w] for w in WORLDS]), 5)]))[0]),
                     'median': pct(rm_sum['median_irr']), 'p5': pct(rm_sum['p5_irr']), 'P15': round(rm_sum['p_ge15'], 3), 'P_loss': round(rm_sum['p_loss'], 3)}
    del rm_sims

    # ── 事前登録どおりのデータ（FANG の試算期間を含む）での主の判定＝是正の影響を見せる ──
    ch_pre = dict(ch)
    fp = D.chain_prereg('FANG')
    ch_pre['FANG'] = dict(ch['FANG'], usd=fp['usd'], jpy=fp['jpy'], segs=fp['segs'], first=fp['first'])
    mu_pre, _ = worlds_all(ch_pre, cost, bg, cg, dg, lam)
    sz_pre = sigma_z(ch_pre)
    sims_pre = simulate(mu_pre, sz_pre, WORLDS)
    summ_pre = {b: summarize_bet(sims_pre[b], WORLDS) for b in BETS}
    order_pre = sorted(elig, key=lambda b: -summ_pre[b]['ce_irr'])
    prereg_literal = {'top5': [(b, pct(summ_pre[b]['ce_irr'])) for b in order_pre[:5]],
                      'FANG': {'CE_γ2': pct(summ_pre['FANG']['ce_irr']), 'worlds': {w: pct(mu_pre[w]['FANG']) for w in WORLDS}},
                      'note': 'NYSE FANG+ の 2014-10〜2017-09（発表前の試算）を含めた事前登録どおりの系列での主の順位（是正の前）'}
    del sims_pre

    # ── 感度 ──
    sens = {}
    for g in (1, 3, 5):
        sens[f'γ={g}'] = rank_ce(sims, WORLDS, g, elig)[0][0]
    for w in WORLDS:
        ws = [x for x in WORLDS if x != w]
        sens[f'世界 {w} を外す'] = rank_ce(sims, ws, GAMMA, elig)[0][0]
    sens['歴史だけ（A1・A2）'] = rank_ce(sims, ['A1', 'A2'], GAMMA, elig)[0][0]
    sens['未来だけ（B・C・D・E）'] = rank_ce(sims, ['B', 'C', 'D', 'E'], GAMMA, elig)[0][0]
    s125 = simulate(mu, sz, WORLDS, sigma_mult=1.25)
    sens['σ×1.25'] = rank_ce(s125, WORLDS, GAMMA, elig)[0][0]
    del s125
    for nm, sh in (('ドル円の期待 −2%/年（円高）', -0.02), ('ドル円の期待 +1%/年', 0.01)):
        sx = simulate(mu, sz, WORLDS, fx_shift=sh)
        sens[nm] = rank_ce(sx, WORLDS, GAMMA, elig)[0][0]
        del sx
    for nm, al in (('D の戻り0%（今の PER が続く）', 0.0), ('D の戻り100%（中央値まで戻る）', 1.0)):
        dg2 = world_d_gross(cg, alpha=al) if d_note is None else dg
        dn2 = {b: dg2[b][0] - cost[b] for b in BETS}
        e2, _ = world_e(ch, cost, bnet, cnet, dn2, lam)
        mu2 = dict(mu, D=dn2, E=e2)
        sx = simulate(mu2, sz, WORLDS)
        sens[nm] = rank_ce(sx, WORLDS, GAMMA, elig)[0][0]
        del sx
    e10, _ = world_e(ch, cost, bnet, cnet, dnet, lam10)
    sx = simulate(dict(mu, E=e10), sz, WORLDS)
    sens['λ を L=10・H=10 から'] = rank_ce(sx, WORLDS, GAMMA, elig)[0][0]
    del sx
    cost_u = costs(user_vehicle=True)
    mu_u = {w: dict(mu[w]) for w in WORLDS}
    for w in WORLDS:
        mu_u[w]['NDX'] = mu[w]['NDX'] - (cost_u['NDX'] - cost['NDX']) if w != 'E' else mu[w]['NDX'] - lam * (cost_u['NDX'] - cost['NDX'])
    sx = simulate(mu_u, sz, WORLDS)
    sens['器の費用をユーザーの今の器（NASDAQ100 は iFreeNEXT 0.495%）で'] = rank_ce(sx, WORLDS, GAMMA, elig)[0][0]
    del sx
    sx = simulate(mu, sz, WORLDS, normal=True, seed_tag='normal')
    sens['z を正規分布にする'] = rank_ce(sx, WORLDS, GAMMA, elig)[0][0]
    del sx

    top = order[0]
    wins = sum(1 for v in sens.values() if v == top)
    near = [b for b in order if summ[top]['ce_irr'] - summ[b]['ce_irr'] <= 0.002]
    pick = top
    if len(near) > 1:
        pick = sorted(near, key=lambda b: (regret[b], cost[b]))[0]
    tsumi_order = sorted(tsumi, key=lambda b: -summ[b]['ce_irr'])
    g1 = rank_ce(sims, WORLDS, 1, elig)
    g5 = rank_ce(sims, WORLDS, 5, elig)

    table = []
    for i, b in enumerate(sorted(BETS, key=lambda x: -summ[x]['ce_irr'])):
        c = D.cost_of(b, 'best')
        table.append({
            'rank_all': i + 1, 'rank_eligible': (order.index(b) + 1) if b in elig else None, 'bet': b, 'ja': D.JA[b],
            'eligible': b in elig, 'tsumitate_ok': b in tsumi,
            'CE_γ2(%/年)': pct(summ[b]['ce_irr']), '中央(%/年)': pct(summ[b]['median_irr']), '5%点(%/年)': pct(summ[b]['p5_irr']),
            'P(≥10%)': round(summ[b]['p_ge10'], 3), 'P(≥15%)': round(summ[b]['p_ge15'], 3), 'P(元本割れ)': round(summ[b]['p_loss'], 3),
            'CE_γ1(%/年)': pct(g1[1].get(b)) if b in elig else None, 'CE_γ5(%/年)': pct(g5[1].get(b)) if b in elig else None,
            '世界(%/年)': {w: pct(mu[w][b]) for w in WORLDS}, '最大の後悔(%/年)': pct(regret[b]),
            'σ(円・%/年)': pct(sz[b][0], 1), 'σの窓': sz[b][2],
            '費用(%/年)': pct(cost[b], 3), '最安の器': (c['vehicle'] + f"（{c['account']}）") if c else D.VEH[b].get('note'),
            'つなぎ': ' ← '.join(f"{s['label']}[{s.get('frm')}〜{s.get('to')}]" for s in ch[b]['segs'] if s.get('months')),
        })
    doc = {
        'generated': datetime.date.today().isoformat(), 'tool': 'night/bestfund.py', 'prereg': PREREG,
        'question': '日本の個人・円で毎月積立・NISA・20〜30年にとって、期待できる20年積立の円建ての最終額が最も大きく、かつ大きく崩れにくい投資信託・ETF（1本）',
        'verdict': {
            'best_bet': pick, 'best_bet_ja': D.JA[pick], 'top_by_ce': top, 'near_tie_within_0.2pt': near,
            'sensitivity_wins': f'{wins}/{len(sens)}', 'robust_70pct': wins / len(sens) >= 0.7,
            'best_tsumitate_bet': tsumi_order[0] if tsumi_order else None,
            'gamma1_top': g1[0][0], 'gamma5_top': g5[0][0],
            'vehicle_best': D.cost_of(pick, 'best'), 'vehicle_tsumitate': D.cost_of(pick, 'tsumitate'), 'vehicle_growth': D.cost_of(pick, 'growth'),
        },
        'sensitivities_top1': sens,
        'prereg_literal_FANG_backtest_included': prereg_literal,
        'reference_current_etf_mix': reference_mix,
        'table': table,
        'worlds_notes': {'A1': a1n, 'A2': a2n, 'C': c_note, 'D': d_note, 'E_lambda': lam, 'E_lambda_L10H10': lam10, 'E_detail': edet,
                         'B_inputs': b_inputs, 'B_src': {b: bg[b][3] for b in BETS},
                         'C_detail': {b: {'avg10': cg[b][1], 'n': cg[b][2]} for b in BETS},
                         'D_detail': {b: dg[b][1] for b in BETS}},
        'H1_yen_dca': h1(ch, cost), 'H2_lump_dd': h2(ch, cost), 'H3_eras': h3(ch, cost),
        'costs': {b: dict(total=pct(cost[b], 3), **({k: v for k, v in (D.cost_of(b, 'best') or {}).items() if k != 'total'})) for b in BETS},
    }
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)
    print(f"{'順':>2} {'賭け':10} {'CE2':>6} {'中央':>6} {'5%点':>6} {'P15':>5} {'損':>5} {'A1':>6} {'A2':>6} {'B':>6} {'C':>6} {'D':>6} {'E':>6} {'後悔':>5} {'σ':>5} {'費用':>6}")
    for t in table:
        if not t['eligible']:
            continue
        w = t['世界(%/年)']
        print(f"{t['rank_eligible']:2d} {t['bet']:10} {t['CE_γ2(%/年)']:6.2f} {t['中央(%/年)']:6.2f} {t['5%点(%/年)']:6.2f} {t['P(≥15%)']:5.2f} {t['P(元本割れ)']:5.2f} "
              f"{w['A1']:6.2f} {w['A2']:6.2f} {w['B']:6.2f} {w['C']:6.2f} {w['D']:6.2f} {w['E']:6.2f} {t['最大の後悔(%/年)']:5.2f} {t['σ(円・%/年)']:5.1f} {t['費用(%/年)']:6.3f}")
    print('参考 今のETF側:', reference_mix)
    print('事前登録どおり（FANG 試算込み）:', prereg_literal)
    print('判定:', doc['verdict'])
    print('感度:', sens)


if __name__ == '__main__':
    main()
