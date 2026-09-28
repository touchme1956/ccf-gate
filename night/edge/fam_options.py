#!/usr/bin/env python3
"""night/edge/fam_options.py — 系統 options（第10回）: オプション戦略の指数を持ち続ける vs 米国市場

事前登録 out/edge_prereg_r10.json の families.options。読むだけ・門の採点に不使用。
  データ: CBOE の戦略指数（日次の終値・cdn.cboe.com/api/global/us_indices/daily_prices/{名}_History.csv）
    BXMD  S&P500 を持ち、30デルタの1か月コールを売る（カバードコール）
    BXY   S&P500 を持ち、2%外の1か月コールを売る（1988-06〜）
    CMBO  S&P500 を持ち、外のコールを売り外のプットを売る（コンボ）
    PPUT  S&P500 を持ち、5%外の1か月プットを買う（プロテクティブ・プット）
    RXM   リスク・リバーサル（コールを買いプットを売る・短期国債で担保）
    CNDR  アイアン・コンドルを売る（短期国債で担保）
    BFLY  アイアン・バタフライを売る（短期国債で担保）
    PUT   S&P500 の1か月アットのプットを売る（短期国債で担保）＝ Yahoo の ^PUT（1996-08〜・CBOE の CSV は2001年より前が抜けている）
  月次リターン = 月の最後の取引日の終値の比。指数は売買の費用を含まない → 年0.60%（XYLD・QYLD の経費率）を毎月引く（事前登録）。
  1.5倍（PUT・BXMD・BXY）: 毎月リセット・借りた分 0.5 に 短期金利＋0.4%/年、経費 0.9%/年（事前登録の costs.レバレッジ）。
  相手: French の米国市場。

★先読み: 規則は「その指数を持ち続ける」だけで、信号は無い（月 m の持ち物は固定）。月次リターンは月末の値だけから作る。
使い方: python3 night/edge/fam_options.py           → 変種の表（選定の段・2000-12 まで）
        python3 night/edge/fam_options.py --save    → 選んで凍結（out/edge/spec_options.json）
"""
import sys, os, csv, io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h  # noqa: E402

FAMILY = {
    'key': 'options',
    'name': 'オプション戦略の指数（カバードコール・プット売り・プロテクティブ・プット等）を持ち続ける',
    'implement': ('楽天証券の海外ETFで買えるのはカバードコール型（XYLD＝S&P500・QYLD＝NASDAQ100・RYLD＝ラッセル2000・JEPI・JEPQ）。'
                  'プット売りの ETF（PUTW）は取扱が無い（しかも2023年に償還）。オプションを自分で売る取引は NISA では不可、'
                  '楽天の米国株オプションの個人取引も無い。カバードコールETFは分配金が多く、課税口座では毎年課税される。'),
}
CBOE = 'https://cdn.cboe.com/api/global/us_indices/daily_prices/{}_History.csv'
FEE = 0.006
LEV_SPREAD, LEV_FEE = 0.004, 0.009
INDICES = ['BXMD', 'BXY', 'CMBO', 'PPUT', 'RXM', 'CNDR', 'BFLY', 'PUT']
LEVERED = ['PUT', 'BXMD', 'BXY']


def monthly_levels(name):
    """{YYYYMM: 月の最後の取引日の終値}（h.guard 済み）"""
    if name == 'PUT':
        return h.yahoo('^PUT', 1986)
    raw = h.cached(f'cboe_{name}.csv', CBOE.format(name), 30).decode()
    last = {}
    for row in list(csv.reader(io.StringIO(raw)))[1:]:
        if len(row) < 2 or not row[1]:
            continue
        mo, d, y = row[0].split('/')
        k = int(y) * 10000 + int(mo) * 100 + int(d)
        try:
            v = float(row[1])
        except ValueError:
            continue
        m = k // 100
        if m not in last or k > last[m][0]:
            last[m] = (k, v)
    return h.guard({m: v for m, (k, v) in last.items()})


def series(spec, rf):
    lv = monthly_levels(spec['index'])
    r = h.px_to_ret(lv)
    ks = sorted(r)
    if ks:                                           # 最初の月は指数の始まり（途中の月）なので落とす
        r.pop(ks[0], None)
    L = spec.get('lev', 1.0)
    out = {}
    for m, x in r.items():
        if m not in rf:
            continue
        y = L * x - (L - 1) * (rf[m] + LEV_SPREAD / 12) - ((L - 1) * LEV_FEE / 12 if L > 1 else 0.0)
        out[m] = y - FEE / 12
    return out


def run(spec):
    mkt, rf = h.us_market()
    ret = {m: v for m, v in series(spec, rf).items() if m in mkt}
    return {'ret': ret, 'bench': {m: mkt[m] for m in ret}, 'rf': rf, 'turnover': {m: 0.0 for m in ret}, 'cost': 0.0}


def variants():
    vs = [{'index': i, 'lev': 1.0} for i in INDICES]
    vs += [{'index': i, 'lev': 1.5} for i in LEVERED]
    return vs


def main():
    assert h.PHASE == 'select'
    rows = []
    for v in variants():
        r = run(v)
        st = h.stats(r['ret'], r['bench'], r['rf'], b=h.SEL_END)
        rows.append((v, st))
        s = st or {}
        print(f"{v['index']:5} x{v['lev']}  {s.get('from')}〜{s.get('to')}  年率 {s.get('cagr')} vs {s.get('bench_cagr')}  超過 {s.get('excess')} t{s.get('t')}  "
              f"ぶれ {s.get('vol')}/{s.get('bench_vol')}  最大下落 {s.get('maxdd')}/{s.get('bench_maxdd')}")
    if '--save' in sys.argv:
        ok = [(v, s) for v, s in rows if s]
        good = [(v, s) for v, s in ok if s['excess'] >= 1.0]
        pool = good or ok
        v, s = max(pool, key=lambda z: z[1]['t'] if z[1]['t'] is not None else -99)
        note = '' if good else '⚠ 選定期間で +1%/年 に届いた変種は0 → 事前登録どおり t 最大の変種を凍結した（選定期間でも負けているので判定の条件3で落ちる見込み）。'
        doc = h.save_spec('options', v,
                          f"【規則】{v['index']} を {v['lev']}倍で持ち続ける（経費 年0.60%、1.5倍は借入 短期金利＋0.4%・経費0.9%）。"
                          f"【なぜ】オプションの売り手はリスクの対価（分散のプレミアム）を受け取るという説（Whaley 2002 の BXM・Coval & Shumway 2001・Bakshi & Kapadia 2003）。{note}",
                          len(rows), s, {'variants_table': [{'spec': a, 'stats': b} for a, b in rows]})
        print('凍結:', doc['spec'])


if __name__ == '__main__':
    main()
