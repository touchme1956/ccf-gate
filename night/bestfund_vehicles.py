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


def ann(r, ks):
    if not ks or any(k not in r for k in ks):
        return None
    return math.exp(math.fsum(math.log1p(r[k]) for k in ks) * 12 / len(ks)) - 1


def last_months(n, end=D.END):
    out, y, m = [], end // 100, end % 100
    for _ in range(n):
        out.append(y * 100 + m)
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return sorted(out)


def vehicle_monthly_jpy(kind, key):
    if kind in ('fund', 'jp'):
        return D.jita_monthly(key[0], key[1])
    return D.to_jpy(D.yahoo_tr(key))


def compare(bet):
    ch = D.chains()
    idx = ch[bet]['jpy']
    v = D.VEH[bet]
    rows = []
    for nm, kind, key, tsumi, grow, er in CANDS.get(bet, []):
        r = vehicle_monthly_jpy(kind, key)
        e = {'vehicle': nm, 'kind': kind, 'tsumitate': tsumi, 'growth': grow, 'listed_fee': round(100 * er, 4)}
        for yrs in (3, 5):
            ks = last_months(12 * yrs)
            a, b = ann(r, ks), ann(idx, ks)
            if a is None or b is None:
                e[f'td_{yrs}y'] = None
                continue
            td = a - b
            extra = (v['k'] * v['dy'] + D.FX_FEE) if kind == 'us' else 0.0
            e[f'td_{yrs}y'] = round(100 * td, 3)
            e[f'cost_{yrs}y'] = round(100 * (-td + extra), 3)
        c = e.get('cost_5y') if e.get('cost_5y') is not None else e.get('cost_3y')
        e['cost_used'] = c
        e['cost_basis'] = '5年' if e.get('cost_5y') is not None else ('3年' if e.get('cost_3y') is not None else '記録が3年未満＝表の経費率＋外国税')
        if c is None:
            e['cost_used'] = round(100 * (er + v['k'] * v['dy'] + (D.FX_FEE if kind == 'us' else 0.0)), 3)
        rows.append(e)
    best = {}
    for acct, flag in (('つみたて', 'tsumitate'), ('成長', 'growth')):
        cand = [x for x in rows if x[flag] and x['cost_used'] is not None]
        if cand:
            best[acct] = min(cand, key=lambda x: x['cost_used'])['vehicle']
    return {'bet': bet, 'ja': D.JA[bet], 'vehicles': rows, 'best': best}


def main(bets=None):
    if not bets:
        doc = json.load(open(os.path.join(BASE, 'out', 'bestfund.json')))
        bets = [t['bet'] for t in doc['table'] if t['eligible']][:5]
    res = {'generated': datetime.date.today().isoformat(), 'tool': 'night/bestfund_vehicles.py', 'prereg': 'out/bestfund_prereg.json（d5eab7f）H5',
           'bets': [compare(b) for b in bets],
           '⚠': ['日本の投信は米国の前日の終値・当日のドル円で基準価額が決まる＝月次の差は1日ずれの雑音を含む（年率は3年・5年でならした）',
                 '指数の円建ては FRED のドル円（ニューヨーク正午）で換算。投信は東京のその日のレート＝わずかにずれる',
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
