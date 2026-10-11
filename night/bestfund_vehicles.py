#!/usr/bin/env python3
"""night/bestfund_vehicles.py — bestfund の H5: 同じ賭けの器（投資信託・米国ETF・東証ETF）の実際の費用を比べる（読むだけ）

事前登録 out/bestfund_prereg.json（d5eab7f）historical_tests.H5 どおり。最終候補の上位5つの賭けについて、
  費用 ＝ 実際の連動の差（器の円建ての総リターン − 指数の円建ての総リターン・直近3年と5年の年率）を符号を返したもの
        （日本の投信は基準価額に信託報酬・中の米国ETFの経費・源泉の外国税・現金の持ち分が全部入っている）
        ＋ 米国ETF だけ: NISA の中で取り戻せない配当の外国税（k×配当利回り）＋ 両替の手数料（年0.02%）
を出し、つみたて投資枠と成長投資枠で別々に最安を選ぶ。
指数の円建ての総リターンは bestfund_data のつなぎ（実物の期間は器の経費率を足し戻した『指数の値』）をドル円で円に直したもの。
日本の投信の基準価額は米国の前日の終値と当日のドル円で決まる（1日ずれる）ので、月次の差には雑音が乗る。年率の差は3年・5年でならす。

  python3 night/bestfund_vehicles.py NDX SEMI_SOX ...   → out/bestfund_vehicles.json（引数なしは out/bestfund.json の上位5）
"""
import datetime, json, math, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import bestfund_data as D      # noqa: E402

OUT = os.path.join(BASE, 'out', 'bestfund_vehicles.json')
# 賭けごとの比べる器: (名前, 種類 fund/us/jp, 取得の鍵, つみたて可, 成長可, 表の経費率〔税込・中のETF込み〕)
# 投信の isin・協会コードと NISA の枠・楽天の取扱は投信総合検索ライブラリー（2026-10-09）で確かめた
CANDS = {
    'NDX': [('iFreeNEXT NASDAQ100インデックス', 'fund', ('JP90C000GUN2', '04317188'), True, True, 0.00495),
            ('楽天・プラス・NASDAQ-100インデックス・ファンド', 'fund', ('JP90C000QF22', '9I314241'), False, True, 0.00198),
            ('ニッセイNASDAQ100インデックスファンド', 'fund', ('JP90C000PDY6', '29313233'), False, True, 0.002035),
            ('eMAXIS NASDAQ100インデックス', 'fund', ('JP90C000L9D2', '0331A211'), False, True, 0.002035),
            ('QQQM', 'us', 'QQQM', False, True, 0.0015), ('QQQ', 'us', 'QQQ', False, True, 0.0020)],
    'SP500': [('eMAXIS Slim 米国株式（S&P500）', 'fund', ('JP90C000GKC6', '03311187'), True, True, 0.000814),
              ('楽天・プラス・S&P500インデックス・ファンド', 'fund', ('JP90C000Q2U6', '9I31223A'), True, True, 0.000770),
              ('SBI・V・S&P500インデックス・ファンド', 'fund', ('JP90C000J569', '89311199'), True, True, 0.000938),
              ('iシェアーズ米国株式（S&P500）インデックス・ファンド', 'fund', ('JP90C0009FQ7', '4831C139'), True, True, 0.000638),
              ('VOO', 'us', 'VOO', False, True, 0.0003)],
    'ACWI': [('eMAXIS Slim 全世界株式（オール・カントリー）', 'fund', ('JP90C000H1T1', '0331418A'), True, True, 0.0005775),
             ('楽天・プラス・オールカントリー株式インデックス・ファンド', 'fund', ('JP90C000Q2W2', '9I31123A'), True, True, 0.000561),
             ('VT', 'us', 'VT', False, True, 0.0006)],
    'USTOT': [('楽天・全米株式インデックス・ファンド', 'fund', ('JP90C000FHD2', '9I312179'), True, True, 0.00162),
              ('eMAXIS Slim 全米株式', 'fund', ('JP90C000PZY9', '03311239'), False, True, 0.000814),
              ('VTI', 'us', 'VTI', False, True, 0.0003)],
    'SEMI_SOX': [('楽天・プラス・SOXインデックス・ファンド', 'fund', ('JP90C000QF30', '9I315241'), False, True, 0.00176),
                 ('ニッセイSOX指数インデックスファンド', 'fund', ('JP90C000PDZ3', '29314233'), False, True, 0.001815)],
    'SEMI_MV': [('SMH', 'us', 'SMH', False, True, 0.0035)],
    'TECH_SPDR': [('XLK', 'us', 'XLK', False, True, 0.0008)],
    'TECH_VGT': [('VGT', 'us', 'VGT', False, True, 0.0009)],
    'FANG': [('iFreeNEXT FANG+インデックス', 'fund', ('JP90C000FZD4', '04311181'), True, True, 0.007755)],
    'MEGAG': [('MGK', 'us', 'MGK', False, True, 0.0005)],
    'GROWTH': [('VUG', 'us', 'VUG', False, True, 0.0003)],
    'KOKUSAI': [('eMAXIS Slim 先進国株式インデックス', 'fund', ('JP90C000ENC5', '03319172'), True, True, 0.000989),
                ('楽天・プラス・先進国株式（除く日本）', 'fund', ('JP90C000QAT0', '9I31323C'), True, True, 0.00088)],
    'TOPIX': [('eMAXIS Slim 国内株式（TOPIX）', 'fund', ('JP90C000ENA9', '03317172'), True, True, 0.00143),
              ('NEXT FUNDS TOPIX（1306）', 'jp', ('JP3027630007', '01312017'), False, True, 0.000968)],
    'EM': [('eMAXIS Slim 新興国株式インデックス', 'fund', ('JP90C000F7H5', '0331C177'), True, True, 0.001518), ('VWO', 'us', 'VWO', False, True, 0.0006)],
    'INDIA': [('たわらノーロード インド株式 Nifty50', 'fund', ('JP90C000RE71', '4731624C'), False, True, 0.002805),
              ('EPI', 'us', 'EPI', False, True, 0.0084)],
}


# 指数の日次（器の円建ての総リターンと比べる相手）: yahoo＝配当込みの指数 / yahoo_er＝同じ指数の米国ETF＋経費率（指数の配当込みが
# Yahoo に無いもの）/ msci＝MSCI の配当込み（NETR）の日次（日本の投信は円、米国ETF はドル）/ price＝価格指数（投信のベンチマーク自身が価格指数）
IDX = {'NDX': ('yahoo_er', 'QQQ', 0.0020), 'SP500': ('yahoo', '^SP500TR'), 'ACWI': ('msci', 892400), 'KOKUSAI': ('msci', 991200),
       'EM': ('msci', 891800), 'SEMI_SOX': ('yahoo_er', 'SOXX', 0.0033), 'SEMI_MV': ('yahoo_er', 'SMH', 0.0035),
       'FANG': ('yahoo', '^NYFANG'), 'USTOT': ('yahoo_er', 'VTI', 0.0003), 'TECH_SPDR': ('yahoo_er', 'XLK', 0.0008),
       'TECH_VGT': ('yahoo_er', 'VGT', 0.0009), 'MEGAG': ('yahoo_er', 'MGK', 0.0005), 'GROWTH': ('yahoo_er', 'VUG', 0.0003),
       'INDIA': ('yahoo_er', 'EPI', 0.0084)}
_cache = {}


def _daily_levels(ret):
    """{yyyymmdd: 日次リターン} → {yyyymmdd: 水準}"""
    lv, x = {}, 1.0
    for k in sorted(ret):
        x *= 1 + ret[k]
        lv[k] = x
    return lv


def idx_daily(bet, ccy):
    key = (bet, ccy)
    if key in _cache:
        return _cache[key]
    import mw_common as M
    spec = IDX[bet]
    if spec[0] == 'msci':
        url = (f'https://app2.msci.com/products/service/index/indexmaster/getLevelDataForGraph?currency_symbol={ccy}&index_variant=NETR'
               f'&start_date=20150101&end_date={D.END}30&data_frequency=DAILY&baseValue=false&index_codes={spec[1]}')
        j = json.loads(M.get(url, name=f'bf_msci_{spec[1]}_NETR_{ccy}_daily_{D.END}.json', max_age_days=30))
        lv = {x['calc_date']: x['level_eod'] for x in j['indexes']['INDEX_LEVELS']}
        out = (lv, ccy)
    else:
        r = M.yahoo(spec[1], interval='1d')
        if spec[0] == 'yahoo_er':
            r = {k: v + spec[2] / 252 for k, v in r.items()}
        out = (_daily_levels(r), 'USD')
    _cache[key] = out
    return out


def fx_daily():
    if 'fx' in _cache:
        return _cache['fx']
    import gaps_common as G, csv, io
    raw = G._cached('fred_DEXJPUS.csv', 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXJPUS').decode()
    fx = {}
    for row in list(csv.reader(io.StringIO(raw)))[1:]:
        if len(row) >= 2 and row[1] not in ('.', ''):
            try:
                fx[int(row[0].replace('-', ''))] = float(row[1])
            except ValueError:
                pass
    _cache['fx'] = fx
    return fx


def _before(sorted_keys, d):
    """d より前で最も近いキー（二分探索）"""
    import bisect
    i = bisect.bisect_left(sorted_keys, d)
    return sorted_keys[i - 1] if i > 0 else None


def window_dates(dates, yrs):
    end = max(k for k in dates if k <= D.END * 100 + 31)
    target = end - yrs * 10000
    cand = [k for k in dates if k >= target]
    return (min(cand), end) if cand else (None, None)


def _rolling_td(levels_v, levels_i, dates, yrs):
    """器と指数の水準（同じ日付の列）から、直近 yrs 年の中の『1年ごとの差』を毎日ずらして平均した年率の差（窓の両端の時刻ずれの雑音をならす）"""
    end = dates[-1]
    start = end - yrs * 10000
    import bisect
    diffs = []
    for i, t in enumerate(dates):
        if t < start + 10000:
            continue
        j = bisect.bisect_left(dates, t - 10000)
        if j >= i or dates[j] < start:
            continue
        s_ = dates[j]
        span = (datetime.date(t // 10000, t // 100 % 100, t % 100) - datetime.date(s_ // 10000, s_ // 100 % 100, s_ % 100)).days / 365.25
        if span < 0.95:
            continue
        diffs.append((math.log(levels_v[t] / levels_v[s_]) - math.log(levels_i[t] / levels_i[s_])) / span)
    if len(diffs) < 100:
        return None
    m = sum(diffs) / len(diffs)
    return math.exp(m) - 1, len(diffs)


def td_fund(bet, isin, assoc, yrs):
    """日本の投信: 基準価額＋分配金の総リターン vs 指数（1日前の米国の終値 × 前日のドル円、MSCI は前営業日の円建て）"""
    rows = [r for r in D.jita_daily(isin, assoc) if r[0] <= D.END * 100 + 31]
    if len(rows) < 300:
        return None
    lv_f, x = {}, 1.0
    lv_f[rows[0][0]] = x
    for (a, n0, _), (b, n1, v1) in zip(rows, rows[1:]):
        x *= (n1 + v1) / n0
        lv_f[b] = x
    dates = [d for d, _, _ in rows]
    if dates[-1] - dates[0] < yrs * 10000:
        return None
    lv, ccy = idx_daily(bet, 'JPY')
    keys = sorted(lv)
    lv_i = {}
    if ccy == 'JPY':
        for d in dates:
            k = _before(keys, d)
            if k:
                lv_i[d] = lv[k]
    else:
        fx = fx_daily()
        fk = sorted(fx)
        for d in dates:
            k, f = _before(keys, d), _before(fk, d)
            if k and f:
                lv_i[d] = lv[k] * fx[f]
    dd = [d for d in dates if d in lv_i]
    res = _rolling_td(lv_f, lv_i, dd, yrs)
    if res is None:
        return None
    return res[0], dd[0] if dd[0] > dd[-1] - yrs * 10000 else dd[-1] - yrs * 10000, dd[-1]


def td_us(bet, tick, yrs):
    import mw_common as M
    r = {k: v for k, v in M.yahoo(tick, interval='1d').items() if k <= D.END * 100 + 31}
    lv_e = _daily_levels(r)
    dates = sorted(lv_e)
    if dates[-1] - dates[0] < yrs * 10000:
        return None
    lv, ccy = idx_daily(bet, 'USD')
    keys = sorted(lv)
    lv_i = {}
    for d in dates:
        k = _before(keys, d + 1)
        if k:
            lv_i[d] = lv[k]
    dd = [d for d in dates if d in lv_i]
    res = _rolling_td(lv_e, lv_i, dd, yrs)
    if res is None:
        return None
    return res[0], dd[-1] - yrs * 10000, dd[-1]


def compare(bet):
    v = D.VEH[bet]
    rows = []
    for nm, kind, key, tsumi, grow, er in CANDS.get(bet, []):
        e = {'vehicle': nm, 'kind': kind, 'tsumitate': tsumi, 'growth': grow, 'listed_fee': round(100 * er, 4)}
        extra = (v['k'] * v['dy'] + D.FX_FEE) if kind == 'us' else 0.0
        for yrs in (3, 5):
            res = None
            if bet in IDX:
                res = td_fund(bet, key[0], key[1], yrs) if kind in ('fund', 'jp') else td_us(bet, key, yrs)
            if res is None:
                e[f'td_{yrs}y'] = None
                continue
            td, a, b = res
            e[f'td_{yrs}y'] = round(100 * td, 3)
            e[f'cost_{yrs}y'] = round(100 * (-td + extra), 3)
            e[f'window_{yrs}y'] = f'{a}〜{b}'
        c = e.get('cost_5y') if e.get('cost_5y') is not None else e.get('cost_3y')
        e['cost_basis'] = '5年' if e.get('cost_5y') is not None else ('3年' if e.get('cost_3y') is not None else '記録が3年未満（または指数の日次が無い）＝表の経費率＋外国税')
        e['cost_used'] = c if c is not None else round(100 * (er + v['k'] * v['dy'] + (D.FX_FEE if kind == 'us' else 0.0)), 3)
        rows.append(e)
    best = {}
    for acct, flag in (('つみたて', 'tsumitate'), ('成長', 'growth')):
        cand = [x for x in rows if x[flag] and x['cost_used'] is not None]
        if cand:
            best[acct] = min(cand, key=lambda x: x['cost_used'])['vehicle']
    return {'bet': bet, 'ja': D.JA[bet], 'index_for_td': IDX.get(bet), 'vehicles': rows, 'best': best}


def main(bets=None):
    if not bets:
        doc = json.load(open(os.path.join(BASE, 'out', 'bestfund.json')))
        bets = [t['bet'] for t in doc['table'] if t['eligible']][:5]
    res = {'generated': datetime.date.today().isoformat(), 'tool': 'night/bestfund_vehicles.py', 'prereg': 'out/bestfund_prereg.json（d5eab7f）H5',
           'bets': [compare(b) for b in bets],
           '⚠': ['日本の投信は米国の前日の終値・当日のドル円で基準価額が決まる＝月次の差は1日ずれの雑音を含む（年率は3年・5年でならした）',
                 '日本の投信は『1日前の米国の終値 × 前日のドル円（FRED・ニューヨーク正午）』、MSCI の指数は前営業日の円建ての値と比べた（基準価額の決まり方に時刻を合わせる）',
                 '米国ETF は配当の外国税（NISA で戻らない 10%×配当利回り）と両替の手数料（年0.02%）を足した']}
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
    for b in res['bets']:
        print(f"== {b['bet']} {b['ja']}  最安: {b['best']}")
        for x in b['vehicles']:
            print(f"   {x['vehicle'][:40]:40} 表{x['listed_fee']:.3f}% 連動3年{x.get('td_3y')} 5年{x.get('td_5y')} → 費用{x['cost_used']}%（{x['cost_basis']}）")
    print('→', OUT)
    return res


if __name__ == '__main__':
    main(sys.argv[1:])
