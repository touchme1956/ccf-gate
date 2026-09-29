#!/usr/bin/env python3
"""night/edge/fam_assetclass.py — 系統 assetclass（第10回）: 株以外の資産（金・コモディティ・不動産・米長期国債）を持つ vs 米国市場

事前登録 out/edge_prereg_r10.json の families.assetclass。読むだけ・門の採点に不使用。
  データ（すべて h.guard 済み）:
    GOLD   World Bank Pink Sheet（CMO-Historical-Data-Monthly.xlsx）の Gold（$/トロイオンス）。⚠ 月の平均価格（1960〜）
           ⚠ 1971年8月まで公定価格 $35 に縛られていた（選定期間に入る・事前登録どおり除かない）。⚠ このファイルは 2024-12 まで
    GSCI   Yahoo ^SPGSCI（1985〜）。⚠ 事前登録どおり先物の超過リターンの指数として扱い、短期金利（French RF）を足す
    REIT   Fidelity Real Estate Investment（FRESX）の adjclose（1986〜・分配込み・経費込み）
    LTB    Vanguard Long-Term Treasury（VUSTX）の adjclose（1986〜）
  変種: 4資産それぞれ100%、米国株（French 市場）50%＋その資産50%（毎月戻す）＝8
  費用: 経費 年0.20%（REIT・LTB は投信の経費が価格に入っているので引かない）＋回転1あたり 0.10%（50/50 の戻し）。相手: French の米国市場。
★先読み: 信号は無い（持ち物は固定）。
使い方: python3 night/edge/fam_assetclass.py [--save]
"""
import sys, os, io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h  # noqa: E402

FAMILY = {
    'key': 'assetclass',
    'name': '株以外の資産（金・コモディティ・不動産・米長期国債）を持つ／米国株と半々',
    'implement': ('楽天証券の海外ETF: 金＝GLD・IAU、コモディティ＝GSG・DBC、米長期国債＝TLT 等（NISA 成長投資枠で可のものが多い）。'
                  '米国の REIT ETF（VNQ）は楽天の一覧に無い（東証の J-REIT・米国REIT の投信はある）。'),
}
WB = 'https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/CMO-Historical-Data-Monthly.xlsx'
FEE, COST = 0.002, 0.001


def gold_px():
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(h.cached('wb_cmo_monthly.xlsx', WB, 60)), read_only=True)
    ws = wb['Monthly Prices']
    col, out = None, {}
    for row in ws.iter_rows(values_only=True):
        if col is None:
            for j, c in enumerate(row):
                if isinstance(c, str) and c.strip() == 'Gold':
                    col = j
            continue
        k = row[0]
        if isinstance(k, str) and len(k) == 7 and k[4] == 'M' and isinstance(row[col], (int, float)):
            out[int(k[:4]) * 100 + int(k[5:])] = float(row[col])
    return h.guard(out)


def asset_ret(name, rf):
    if name == 'GOLD':
        return {m: v - FEE / 12 for m, v in h.px_to_ret(gold_px()).items()}
    if name == 'GSCI':
        return {m: v + rf[m] - FEE / 12 for m, v in h.px_to_ret(h.yahoo('^SPGSCI', 1970)).items() if m in rf}
    sym = {'REIT': 'FRESX', 'LTB': 'VUSTX'}[name]
    return h.px_to_ret(h.yahoo(sym, 1970))


def run(spec):
    mkt, rf = h.us_market()
    a = asset_ret(spec['asset'], rf)
    ws = spec.get('w_stock', 0.0)
    ret, tv = {}, {}
    for m in sorted(a):
        if m not in mkt:
            continue
        if ws:
            ret[m] = ws * mkt[m] + (1 - ws) * a[m]
            # 月末に 50/50 へ戻す売買: 前の月の値動きでずれた分
            s, x = ws * (1 + mkt[m]), (1 - ws) * (1 + a[m])
            tv[m] = abs(s / (s + x) - ws)
        else:
            ret[m] = a[m]
            tv[m] = 0.0
    return {'ret': ret, 'bench': {m: mkt[m] for m in ret}, 'rf': rf, 'turnover': tv, 'cost': COST}


def variants():
    return [{'asset': a, 'w_stock': w} for w in (0.0, 0.5) for a in ('GOLD', 'GSCI', 'REIT', 'LTB')]


def main():
    assert h.PHASE == 'select'
    rows = []
    for v in variants():
        r = run(v)
        st = h.stats(r['ret'], r['bench'], r['rf'], b=h.SEL_END, turnover=r['turnover'], cost=r['cost'])
        rows.append((v, st))
        s = st or {}
        print(v, f"{s.get('from')}〜{s.get('to')} 年率 {s.get('cagr')} vs {s.get('bench_cagr')} 超過 {s.get('excess')} t{s.get('t')} ぶれ {s.get('vol')}/{s.get('bench_vol')} 最大下落 {s.get('maxdd')}/{s.get('bench_maxdd')}")
    if '--save' in sys.argv:
        ok = [(v, s) for v, s in rows if s]
        good = [(v, s) for v, s in ok if s['excess'] >= 1.0]
        v, s = max(good or ok, key=lambda z: z[1]['t'] if z[1]['t'] is not None else -99)
        note = '' if good else '⚠ 選定期間で +1%/年 に届いた変種は0 → 事前登録どおり t 最大の変種を凍結した（選定期間でも負けているので条件3で落ちる見込み）。'
        doc = h.save_spec('assetclass', v,
                          f"【規則】{v}。【なぜ】株と相関の低い資産は、持つだけで長期の上乗せがあるという説（コモディティ先物のリスクの対価 Gorton & Rouwenhorst 2006・"
                          f"不動産・長期国債の期間の対価）。{note}",
                          len(rows), s, {'variants_table': [{'spec': a, 'stats': b} for a, b in rows]})
        print('凍結:', doc['spec'])


if __name__ == '__main__':
    main()
