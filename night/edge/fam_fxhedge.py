#!/usr/bin/env python3
"""night/edge/fam_fxhedge.py — 系統 fxhedge: 円で米国株を持つ投資家の為替ヘッジを信号で決める（事前登録 out/edge_prereg.json・第3回）

考え方
  ヘッジなしの円リターン = (1+r_usd)×(P_m / P_{m−1}) − 1        P = 1ドルの円の値段（月末・FRED DEXJPUS）
  ヘッジありの円リターン = (1+r_usd)×(1 + i_loc/1200 − rf_us) − 1  （gaps_yen.py と同じ式・前月末に1か月の予約を組む）
  毎月、m−1 月末までの信号でヘッジ比率 hr∈[0,1] を決め、ret = hr×ヘッジあり + (1−hr)×ヘッジなし。
  相手 = ヘッジなし（hr=0）。二つの差は「ドルを持つことの超過リターン」c = P_m/P_{m−1} − 1 + rf_us − i_loc/1200 の符号を当てる賭け。

信号（すべて m−1 月末までの値だけ）
  spot_mom k      … ドル円の k か月の変化が負ならヘッジ（通貨の勢い: Okunev & White 2003, Menkhoff et al. 2012）
  xr_mom k        … 金利差込みのドルの超過リターン c の k か月累積が負ならヘッジ（勢いを『持つ損得』で測る）
  ma n            … 月末のドル円が n か月平均を下回ればヘッジ（Faber 型のトレンド）
  carry           … 自国の金利 ≥ 米国の金利（ヘッジが只か得）ならヘッジ（先渡しプレミアムの謎: Fama 1984）
  value_chg n     … 実質のドル高（ドル円×米CPI÷自国CPI）の n か月変化が正ならヘッジ（Asness-Moskowitz-Pedersen 2013）
  value_dev n     … 実質ドル円が n か月平均より高ければヘッジ（購買力平価への回帰）
  value_ppp       … 実質ドル円が始点からの累積平均より高ければヘッジ
  eq_ma n / eq_mom k … 米国株が下げ基調ならヘッジ（安全通貨の円は株安で買われる: Ranaldo & Söderlind 2010）
  vote …           … 複数の信号の平均＝部分ヘッジ
  const x         … 常にヘッジ比率 x（参照）
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h

FAMILY = {
    'key': 'fxhedge',
    'name': '為替ヘッジの切り替え（円で持つ米国株・ドル円の信号でヘッジあり⇄なし）',
    'implement': ('同じ指数の「為替ヘッジあり」と「為替ヘッジなし」を月末に入れ替える。東証ETFなら S&P500: 2563（iシェアーズ・ヘッジあり）⇄1655/2558（ヘッジなし）、'
                  'NASDAQ100: 2569（上場インデックスファンド・ヘッジあり）⇄2568（ヘッジなし）など。投信なら同じ運用会社の「ヘッジあり／なし」の対（例 たわらノーロード 先進国株式〈為替ヘッジあり〉⇄なし）。'
                  '楽天証券の特定口座で行うのが前提——売るたびに利益に20.315%の税がかかる（主の判定には入れていない）。'
                  'NISA でも東証ETFは成長投資枠で買えるが、売った分の枠はその年のうちに戻らず（翌年に簿価で復活）、年240万円の枠を入れ替えのたびに使うので、残高が大きいと切り替えは事実上できない。'
                  'つみたて投資枠の投信は「ヘッジあり」の品ぞろえが少なく、同じ理由で切り替えに向かない。部分ヘッジ（投票型）は両方の商品を比率で持つ。'),
}

# 投資家の通貨: FX（FRED 日次→月末値。inv=True は「1外貨あたりのドル」なので逆数にする）と、その国の短期金利（優先順につなぐ）
#   rates: [(FRED の id, この月以降に使う)]。前の候補に値が無い月は次の候補へ落ちる
CCY = {
    'JPY': {'fx': 'DEXJPUS', 'inv': False, 'cpi': ('JPNCPIALLMINMEI', 'M'),
            'rates': [('IRSTCI01JPM156N', 198507), ('INTDSRJPM193N', 0)]},
    'GBP': {'fx': 'DEXUSUK', 'inv': True, 'cpi': ('GBRCPIALLMINMEI', 'M'),
            'rates': [('IR3TIB01GBM156N', 0), ('IRSTCI01GBM156N', 0)]},
    'CHF': {'fx': 'DEXSZUS', 'inv': False, 'cpi': ('CHECPIALLMINMEI', 'M'),
            'rates': [('IR3TIB01CHM156N', 0), ('IRSTCI01CHM156N', 0)]},
    'CAD': {'fx': 'DEXCAUS', 'inv': False, 'cpi': ('CANCPIALLMINMEI', 'M'),
            'rates': [('IR3TIB01CAM156N', 0), ('IRSTCI01CAM156N', 0)]},
    'AUD': {'fx': 'DEXUSAL', 'inv': True, 'cpi': ('AUSCPIALLQINMEI', 'Q'),
            'rates': [('IR3TIB01AUM156N', 0), ('IRSTCI01AUM156N', 0)]},
    'NZD': {'fx': 'DEXUSNZ', 'inv': True, 'cpi': ('NZLCPIALLQINMEI', 'Q'),
            'rates': [('IR3TIB01NZM156N', 0), ('IRSTCI01NZM156N', 0)]},
    'SEK': {'fx': 'DEXSDUS', 'inv': False, 'cpi': ('SWECPIALLMINMEI', 'M'),
            'rates': [('IR3TIB01SEM156N', 0), ('IRSTCI01SEM156N', 0)]},
    'NOK': {'fx': 'DEXNOUS', 'inv': False, 'cpi': ('NORCPIALLMINMEI', 'M'),
            'rates': [('IR3TIB01NOM156N', 0), ('IRSTCI01NOM156N', 0)]},
    'DKK': {'fx': 'DEXDNUS', 'inv': False, 'cpi': ('DNKCPIALLMINMEI', 'M'),
            'rates': [('IR3TIB01DKM156N', 0), ('IRSTCI01DKM156N', 0)]},
    'EUR': {'fx': 'DEXUSEU', 'inv': True, 'cpi': ('CP0000EZ19M086NEST', 'M'),
            'rates': [('IR3TIB01EZM156N', 0), ('IRSTCI01EZM156N', 0)]},
}
US_CPI = ('CPIAUCNS', 'M')
COST = 0.001            # 事前登録: 指数・ETF の入れ替えは片道の回転100%につき 0.10%


def _fred(sid):
    try:
        return h.fred(sid)            # guard 済み
    except Exception:
        return {}


def _rate(ccy):
    """{YYYYMM: 年率%}（候補を優先順につなぐ。月の値は FRED の月次＝その月の平均。前月末の予約には前月の値を使う）"""
    out = {}
    for sid, frm in reversed(CCY[ccy]['rates']):          # 優先度の低い順に上書き
        d = _fred(sid)
        for m, v in d.items():
            if m >= frm:
                out[m] = v
    return out


def _cpi_avail(sid_kind):
    """CPI を『その月末に知っている値』へ並べ替える → {月末 e: 値}。月次は e−2 以前の月、四半期は e−4 以前の期首月（公表の遅れ）"""
    sid, kind = sid_kind
    d = _fred(sid)
    if not d:
        return {}
    lag = 2 if kind == 'M' else 4
    ks = sorted(d)
    out, j, last = {}, 0, None
    m, end = h.add_months(ks[0], lag), h.add_months(ks[-1], lag + 3)
    while m <= end:
        while j < len(ks) and ks[j] <= h.add_months(m, -lag):
            last = d[ks[j]]
            j += 1
        if last is not None:
            out[m] = last
        m = h.add_months(m, 1)
    return h.guard(out)


def load(ccy, need_cpi=False, mkt=None, rf=None, us_rate='tbill'):
    """→ dict: P, un, he, c, il（自国の年率%）, rf（ヘッジの米国側の金利・月次小数）, mkt, Q（実質ドル円・月末 e で知っている値）
    us_rate: 'tbill'＝French の RF（1か月の米国債・既定・事前登録の式）／'interbank'＝米国の3か月銀行間金利（FRED IR3TIB01USM156N の前月）
      ⚠ 為替予約の値段は銀行間の金利で決まる（金利平価）。T-bill は銀行間より低い（1974〜2000 の差 0.5〜1.6%/年）ので、
        'tbill' はヘッジありの円リターンを差の分だけ甘く出す——感度を見るための切り替え"""
    if mkt is None:
        mkt, rf = h.us_market()
    if us_rate == 'interbank':
        ib = _fred('IR3TIB01USM156N')
        rf = {m: ib[h.add_months(m, -1)] / 1200 for m in mkt if h.add_months(m, -1) in ib}
    fx = _fred(CCY[ccy]['fx'])
    P = {m: (1.0 / v if CCY[ccy]['inv'] else v) for m, v in fx.items() if v and v > 0}
    il = _rate(ccy)
    un, he, c = {}, {}, {}
    for m in sorted(mkt):
        p = h.add_months(m, -1)
        if m not in P or p not in P or p not in il or m not in rf:
            continue
        r = mkt[m]
        un[m] = (1 + r) * P[m] / P[p] - 1
        he[m] = (1 + r) * (1 + il[p] / 1200 - rf[m]) - 1
        c[m] = P[m] / P[p] - 1 + rf[m] - il[p] / 1200
    Q = {}
    if need_cpi:
        cu, cl = _cpi_avail(US_CPI), _cpi_avail(CCY[ccy]['cpi'])
        for m, v in P.items():
            if m in cu and m in cl and cl[m] > 0:
                Q[m] = v * cu[m] / cl[m]
    return {'P': P, 'un': un, 'he': he, 'c': c, 'il': il, 'rf': rf, 'mkt': mkt, 'Q': Q}


# ───────────────────────── 信号（m−1 月末までの値だけ） ─────────────────────────
def _back(d, m, k):
    return d.get(h.add_months(m, -k))


def _one(sig, D, m):
    """月 m に使うヘッジ比率（0 or 1、投票なら小数）。材料が無ければ None。見るのは m−1 月末以前だけ"""
    t, a = sig[0], sig[1:]
    e = h.add_months(m, -1)                       # 信号を作る月末
    P, c, Q = D['P'], D['c'], D['Q']
    if t == 'const':
        return a[0]
    if t == 'spot_mom':
        x0, x1 = P.get(e), _back(P, e, a[0])
        return None if x0 is None or x1 is None else float(x0 < x1)
    if t == 'xr_mom':
        ms = [h.add_months(e, -i) for i in range(a[0])]
        if any(x not in c for x in ms):
            return None
        return float(math.prod(1 + c[x] for x in ms) < 1)
    if t == 'ma':
        ms = [h.add_months(e, -i) for i in range(a[0])]
        if any(x not in P for x in ms):
            return None
        return float(P[e] < sum(P[x] for x in ms) / len(ms))
    if t == 'carry':
        il, rf = D['il'].get(e), D['rf'].get(e)
        return None if il is None or rf is None else float(il >= rf * 1200)
    if t == 'value_chg':
        x0, x1 = Q.get(e), _back(Q, e, a[0])
        return None if x0 is None or x1 is None else float(x0 > x1)
    if t == 'value_dev':
        ms = [h.add_months(e, -i) for i in range(a[0])]
        if any(x not in Q for x in ms):
            return None
        return float(Q[e] > sum(Q[x] for x in ms) / len(ms))
    if t == 'value_ppp':                          # 始点からの累積平均（その月末までに知っている値だけ）
        ms = [x for x in Q if x <= e]
        if len(ms) < a[0]:
            return None
        return float(Q[e] > sum(Q[x] for x in ms) / len(ms))
    if t in ('eq_ma', 'eq_mom'):
        idx = D.setdefault('_eqidx', {})
        if not idx:
            v = 1.0
            for x in sorted(D['mkt']):
                v *= 1 + D['mkt'][x]
                idx[x] = v
        if t == 'eq_ma':
            ms = [h.add_months(e, -i) for i in range(a[0])]
            if any(x not in idx for x in ms):
                return None
            return float(idx[e] < sum(idx[x] for x in ms) / len(ms))
        x0, x1 = idx.get(e), _back(idx, e, a[0])
        if x0 is None or x1 is None:
            return None
        rfk = math.prod(1 + D['rf'].get(h.add_months(e, -i), 0.0) for i in range(a[0]))
        return float(x0 / x1 < rfk)
    raise ValueError(sig)


def hedge_ratio(spec, D, m):
    """spec['signal']: 一つの信号 [type, arg…] か、{'vote': [信号…]}（平均）か、{'any': [...]}（どれか一つでも→ヘッジ）か {'all': [...]}"""
    s = spec['signal']
    if isinstance(s, dict):
        (mode, parts), = s.items()
        vals = [_one(tuple(p), D, m) for p in parts]
        if any(v is None for v in vals):
            return None
        if mode == 'vote':
            return sum(vals) / len(vals)
        if mode == 'any':
            return float(max(vals) > 0)
        if mode == 'all':
            return float(min(vals) > 0)
        raise ValueError(mode)
    return _one(tuple(s), D, m)


def _needs_cpi(spec):
    s = spec['signal']
    parts = next(iter(s.values())) if isinstance(s, dict) else [s]
    return any(p[0].startswith('value') for p in parts)


def build(spec, D, start):
    """→ ret, bench, rf(自国の短期金利・月次小数), turnover, hr"""
    ret, bench, rfl, tv, hr = {}, {}, {}, {}, {}
    prev = 0.0                                     # 始めはヘッジなし（相手と同じ）から
    for m in sorted(D['un']):
        if m < start:
            continue
        x = hedge_ratio(spec, D, m)
        if x is None:
            x = 0.0                                # 材料がそろうまではヘッジなし（相手と同じ）
        ret[m] = x * D['he'][m] + (1 - x) * D['un'][m]
        bench[m] = D['un'][m]
        rfl[m] = D['il'][h.add_months(m, -1)] / 1200
        tv[m] = abs(x - prev)
        hr[m] = x
        prev = x
    return ret, bench, rfl, tv, hr


def run(spec):
    mkt, rf = h.us_market()
    start = spec.get('start', 197401)
    cpi = _needs_cpi(spec)
    usr = spec.get('us_rate', 'tbill')
    D = load('JPY', cpi, mkt, rf, usr)
    ret, bench, rfl, tv, _ = build(spec, D, start)
    markets = {}
    for ccy in spec.get('markets', []):
        try:
            Dx = load(ccy, cpi, mkt, rf, usr)
            r2, b2, f2, t2, _ = build(spec, Dx, start)
        except Exception:
            continue
        if len(r2) >= 24:
            markets[f'{ccy}の投資家'] = {'ret': r2, 'bench': b2, 'rf': f2, 'turnover': t2, 'cost': COST}
    return {'ret': ret, 'bench': bench, 'rf': rfl, 'turnover': tv, 'cost': COST, 'markets': markets}
