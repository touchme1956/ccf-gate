#!/usr/bin/env python3
"""night/edge/fam_smallvalue.py — 系統 smallvalue（第2回）: 小型株の「良い側」だけを買う（買いだけ・レバレッジなし）

事前登録 out/edge_prereg.json の決まりどおり。読み込みは harness（french / us_market / french_region）だけ。
  脚（legs）＝ Ken French の規模×特徴の組の SMALL 側（NYSE 中央値より下＝小型株ETFで買える大きさ・時価加重）
    sv    : 6_Portfolios_2x3              SMALL HiBM        （割安・Fama-French 1992）
    smom  : 6_Portfolios_ME_Prior_12_2    SMALL HiPRIOR     （勢い 12-2・Jegadeesh-Titman 1993）
    sop   : 6_Portfolios_ME_OP_2x3        SMALL HiOP        （収益性・Novy-Marx 2013 / FF 2015）
    sinv  : 6_Portfolios_ME_INV_2x3       SMALL LoINV       （投資の控えめ・Titman-Wei-Xie 2004 / FF 2015）
    svop  : 32_Portfolios_ME_BEME_OP_2x4x4  SMALL HiBM HiOP  （割安∧収益性の交わり）
    svinv : 32_Portfolios_ME_BEME_INV_2x4x4 SMALL HiBM LoINV
    sopinv: 32_Portfolios_ME_OP_INV_2x4x4   SMALL HiOP LoINV
  相手 = 米国市場（h.us_market＝French の CRSP 全上場の時価加重）。費用 = 片道の回転1あたり 0.25%。
  回転は事前登録どおり置く: 会計の信号 50%/年・価格の信号（勢い）200%/年（月に均す）＋脚どうしの入れ替え・戻しの実額。

★先読みの禁止: 月 m の持ち高は m−1 月末までのリターンだけで決める（_path の中で hist=… < m に限る）。
  自己検査 selftest() が「m0 以降のリターンを乱数に替えても、m0 までの持ち高・リターンが1ビットも変わらない」ことを確かめる。
"""
import sys, os, math, random, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h

FAMILY = {
    'key': 'smallvalue',
    'name': '小型株の良い側だけを買う（割安・勢い・収益性・投資の控えめ）',
    'implement': ('楽天証券の米国株口座で小型株のファクターETFを買う: 割安＝VBR（Vanguard 小型バリュー・0.07%）/ IJS（iShares S&P 600 バリュー）/ '
                  'AVUV（Avantis 小型バリュー＝割安∧収益性・0.25%）、勢い＝XSMO（Invesco S&P 小型モメンタム）、収益性＝XSHQ（S&P 小型クオリティ）/ AVUV、'
                  '投資の控えめ＝直接の ETF は無く AVUV・DFSV で近似。いずれも成長投資枠（NISA）で買える米国上場ETF。'
                  '脚を等分に持つ規則なら毎月（または年1回）比率を戻すだけ。勢いで脚を入れ替える規則なら月末に ETF を売買（課税口座では売却益に約20%）。'),
}

COST = 0.0025                      # 個別株の組（French の分位）: 片道の回転100%につき 0.25%
TURN = {'acct': 0.50 / 12, 'price': 2.00 / 12, 'mkt': 0.0}   # 月あたりの中の回転（事前登録の置き値）

LEGS = {   # key: (US のファイル, 列, 信号の種類, 地域のファイルの型)
    'sv':     ('6_Portfolios_2x3',               'SMALL HiBM',       'acct',  '{r}_6_Portfolios_ME_BE-ME'),
    'smom':   ('6_Portfolios_ME_Prior_12_2',     'SMALL HiPRIOR',    'price', '{r}_6_Portfolios_ME_Prior_12_2'),
    'sop':    ('6_Portfolios_ME_OP_2x3',         'SMALL HiOP',       'acct',  '{r}_6_Portfolios_ME_OP'),
    'sinv':   ('6_Portfolios_ME_INV_2x3',        'SMALL LoINV',      'acct',  '{r}_6_Portfolios_ME_INV'),
    'svop':   ('32_Portfolios_ME_BEME_OP_2x4x4', 'SMALL HiBM HiOP',  'acct',  '{r}_32_Portfolios_ME_BE-ME_OP_2x4x4'),
    'svinv':  ('32_Portfolios_ME_BEME_INV_2x4x4', 'SMALL HiBM LoINV', 'acct', None),
    'sopinv': ('32_Portfolios_ME_OP_INV_2x4x4',  'SMALL HiOP LoINV', 'acct',  None),
}

# 再現に使う地域（互いに重ならない地域だけ。North America は米国が9割で独立でない・Developed/Developed_ex_US はこれらの合計なので入れない）
REGIONS = ['Europe', 'Japan', 'Asia_Pacific_ex_Japan', 'Emerging_Markets']


def _vw_monthly(tables):
    """French の表のうち『Value Weight … Monthly』の表 → {列: {YYYYMM: 小数}}"""
    t = next(k for k in tables if 'Value Weight' in k and 'Monthly' in k)
    return {c: {m: v / 100 for m, v in s.items() if 99999 < m < 1000000} for c, s in tables[t].items()}


def _leg(key, region=None):
    f, col, _, rf = LEGS[key]
    name = f if region is None else (rf.format(r=region) if rf else None)
    if name is None:
        raise KeyError(f'{key} は {region} に無い')
    return _vw_monthly(h.french(name))[col]


def _region_market(region):
    if region == 'Emerging_Markets':          # French は新興国の3因子を出していない → 5因子の最初の表（月次）の Mkt-RF＋RF
        d = h.french('Emerging_5_Factors')
        t = next(iter(d))
        mk, rf = d[t]['Mkt-RF'], d[t]['RF']
        return ({m: (mk[m] + rf[m]) / 100 for m in mk if m in rf and 99999 < m < 1000000},
                {m: rf[m] / 100 for m in rf if 99999 < m < 1000000})
    return h.french_region(region)


# ───────────────────────── 規則の本体（先読みなし） ─────────────────────────
def _sd(xs):
    n = len(xs)
    mu = sum(xs) / n
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1))


def _cum(r, ms):
    return math.prod(1 + r[x] for x in ms)


def _target(legs, mkt, spec, m, sleeve_hist):
    """月 m の目標の持ち高 {名前: 重み}。使ってよいのは キー < m のデータだけ（ここで必ず切る）"""
    names = spec['legs']
    prev = [h.add_months(m, -k) for k in range(1, 61)]             # m−1, m−2, … （過去だけ）
    avail = [k for k in names if m in legs[k]]                          # その月に組が存在する（組の開始日は構造的に既知）
    if spec.get('start', 'common') == 'common' and len(avail) < len(names):
        return None
    if not avail:
        return None
    rot = spec.get('rotate')
    wmode = spec.get('weight', 'equal')
    if rot:
        L, top = rot['lookback'], rot['top']
        el = [k for k in avail if all(x in legs[k] for x in prev[:L])]
        if not el:
            return None
        sc = {k: _cum(legs[k], prev[:L]) for k in el}
        pick = sorted(el, key=lambda k: (-sc[k], names.index(k)))[:top]
        w = {k: 1 / len(pick) for k in pick}
    elif wmode == 'invte':
        W = spec.get('te_window', 36)
        el, inv = [], {}
        for k in avail:
            hist = [x for x in prev[:W] if x in legs[k] and x in mkt]
            if len(hist) < 24:
                continue
            te = _sd([legs[k][x] - mkt[x] for x in hist])
            if te > 0:
                inv[k] = 1 / te
        if not inv:
            return None
        tot = sum(inv.values())
        w = {k: v / tot for k, v in inv.items()}
    else:
        w = {k: 1 / len(avail) for k in avail}
    ov = spec.get('overlay')
    if ov == 'mkt_trend10':                  # 市場の配当込み指数が 10か月平均を下回ったら 市場を持つ
        ms10 = prev[:10]
        if not all(x in mkt for x in ms10):
            return None
        idx, v = {}, 1.0
        for x in sorted(ms10):
            v *= 1 + mkt[x]
            idx[x] = v
        if idx[prev[0]] < S.mean(idx.values()):
            w = {'MKT': 1.0}
    elif ov == 'relmom12':                   # 脚の合成（重ねる前）の直近12か月が市場に負けていたら 市場を持つ
        ms12 = prev[:12]
        if not all(x in sleeve_hist and x in mkt for x in ms12):
            return None
        if _cum(sleeve_hist, ms12) < _cum(mkt, ms12):
            w = {'MKT': 1.0}
    elif ov == 'bear24':                     # 市場の直近24か月が負（弱気の局面・Cooper-Gutierrez-Hameed 2004 / Daniel-Moskowitz 2016）なら alt を持つ
        ms24 = prev[:24]
        if not all(x in mkt for x in ms24):
            return None
        if _cum(mkt, ms24) < 1.0:
            alt = spec.get('alt', 'MKT')
            if alt != 'MKT' and m not in legs.get(alt, {}):
                return None
            w = {alt: 1.0}
    elif ov == 'volman':                     # 追従のぶれ（直近12か月）が過去の中央値より大きい月は、その分だけ市場へ寄せる（Barroso-Santa-Clara 2015 の買いだけ版）
        ex = {x: sleeve_hist[x] - mkt[x] for x in sleeve_hist if x in mkt and x < m}
        def te(x):
            ws = [h.add_months(x, -j) for j in range(12)]
            return _sd([ex[y] for y in ws]) if all(y in ex for y in ws) else None
        past = [v for v in (te(x) for x in sorted(ex)) if v is not None]
        if len(past) < 36:
            return None
        now = past[-1]
        k = min(1.0, S.median(past) / now) if now > 0 else 1.0
        w = {kk: vv * k for kk, vv in w.items()}
        if k < 1.0:
            w['MKT'] = w.get('MKT', 0.0) + (1.0 - k)
    return w


def _path(legs, mkt, spec):
    """→ (ret, turnover, weights)。月ごとに _target を呼び、実際の脚のリターンで回す"""
    kinds = {k: LEGS[k][2] for k in legs}
    kinds['MKT'] = 'mkt'
    ms = sorted(set(mkt) | set().union(*[set(legs[k]) for k in spec['legs']]))
    ret, tov, wts = {}, {}, {}
    sleeve = {}                  # 重ねる前の合成（relmom12 の信号用）
    base_spec = dict(spec, overlay=None)
    drift = None
    for m in ms:
        if m not in mkt:
            continue
        if spec.get('overlay') in ('relmom12', 'volman'):
            wb = _target(legs, mkt, base_spec, m, sleeve)
            if wb is not None and all(m in legs[k] for k in wb):
                sleeve[m] = sum(wb[k] * legs[k][m] for k in wb)
        w = _target(legs, mkt, spec, m, sleeve)
        if w is None:
            drift = None
            continue
        src = dict(legs, MKT=mkt)
        if not all(m in src[k] for k in w):
            drift = None
            continue
        r = sum(w[k] * src[k][m] for k in w)
        inner = sum(w[k] * TURN[kinds[k]] for k in w)
        trade = 0.5 * sum(abs(w.get(k, 0.0) - drift.get(k, 0.0)) for k in set(w) | set(drift)) if drift is not None else 0.0
        ret[m], tov[m], wts[m] = r, inner + trade, w
        g = {k: w[k] * (1 + src[k][m]) for k in w}
        tot = sum(g.values())
        drift = {k: v / tot for k, v in g.items()} if tot > 0 else None
    return ret, tov, wts


def _need(spec):
    alt = spec.get('alt')
    return list(spec['legs']) + ([alt] if alt and alt != 'MKT' and alt not in spec['legs'] else [])


def run(spec):
    mkt, rf = h.us_market()
    legs = {k: _leg(k) for k in _need(spec)}
    ret, tov, _ = _path(legs, mkt, spec)
    out = {'ret': ret, 'bench': mkt, 'rf': rf, 'turnover': tov, 'cost': COST, 'markets': {}}
    for reg in spec.get('markets', REGIONS):
        try:
            rl = {k: _leg(k, reg) for k in _need(spec)}
        except KeyError:
            continue                           # その地域に組が無い脚を使う規則は、その地域では当てない（名前は spec に残る）
        rm, rrf = _region_market(reg)
        r2, t2, _ = _path(rl, rm, spec)
        out['markets'][reg] = {'ret': r2, 'bench': rm, 'rf': rrf, 'turnover': t2, 'cost': COST}
    return out


# ───────────────────────── 先読みの自己検査 ─────────────────────────
def selftest(spec, n=25, seed=7):
    """m0 以降のすべての脚と市場のリターンを乱数に替えても、m0 以前（m0 を含む持ち高）が変わらないこと"""
    mkt, _ = h.us_market()
    legs = {k: _leg(k) for k in _need(spec)}
    r0, t0, w0 = _path(legs, mkt, spec)
    rnd = random.Random(seed)
    ms = sorted(r0)
    bad = 0
    for m0 in rnd.sample(ms[13:], min(n, len(ms) - 13)):
        lg = {k: {x: (v if x < m0 else rnd.gauss(0.01, 0.08)) for x, v in s.items()} for k, s in legs.items()}
        mk = {x: (v if x < m0 else rnd.gauss(0.01, 0.05)) for x, v in mkt.items()}
        r1, t1, w1 = _path(lg, mk, spec)
        for x in ms:
            if x > m0:
                break
            same_w = w0.get(x) == w1.get(x)
            same_r = x == m0 or abs(r0[x] - r1.get(x, 9)) < 1e-15
            same_t = abs(t0[x] - t1.get(x, 9)) < 1e-15
            if not (same_w and same_r and same_t):
                bad += 1
                break
    # 1か月ずらし: 月 m の持ち高が月 m のリターンを使っていないこと（m0 の持ち高は上で m0 を乱しても不変を確認済み）
    return {'perturbed_months': min(n, len(ms) - 13), 'violations': bad}
