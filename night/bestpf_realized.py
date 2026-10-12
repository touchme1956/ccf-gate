#!/usr/bin/env python3
"""night/bestpf_realized.py — 話に出た組み合わせの「実際の年率」（過去の実績）を並べる（2026-10-12・ユーザー「実際の年率は？」）

読むだけ。門・配分には触れない（portfolio.json は書き換えない）。事前登録の外（結果の表示だけで、何も選ばない）。
系列は bestpf_ext.rank_result() の chains をそのまま使う（＝bestpf_check の『過去の転がる20年で15%以上』と同じ系列・同じ手取りの調整 adj）:
  - ETF は Yahoo の調整後終値（配当込み・ETF の信託報酬は引かれた後）。adj＝器の費用の差と NISA で戻らない配当の外国税（年率を月割りで足す）
  - NASDAQ100 は QQQ→QQQM（1999-04〜）。★iFreeNEXT（0.495%）で持つと年0.35pt ほど下がる（別行で出す）
  - ITA は 2006-05 まで能動の投信 FSDAX でつないだ代理・インド（EPI_LONG）は 2008-02 まで JKP のインド株の代理
組み方: 毎月その比へ組み直す（本物は不足から買い・売らない＝night/rebalance_policy.py の測定で最終額の差は±1.5%以内）。
円: FRED DEXJPUS の月末で円へ（為替ヘッジなし）。
出すもの:
  ① 一括の年率（ドル・円）: 期間ごと（2000-09〜／ITA が実物になった 2006-06〜／インドが実物の 2008-03〜／直近15・10・5・1年）
  ② 毎月の積立の内部収益率: 今日（2026-09）で終わる 20・15・10・5年／転がる20年・15年の窓の 最小・中央・最大と ≥15%・≥10% の割合
  ③ ぶれ・最大下落（2000-09〜・ドルと円）
出力: out/bestpf_realized.json
"""
import datetime, json, math, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'bestpf_realized.json')

PORTS = {
    '今（ETF側の目標）NDX50/SMH20/ITA15': {'QQQM': 50, 'SMH': 20, 'ITA': 15},
    '推奨 NDX50/SMH30/ITA20': {'QQQM': 50, 'SMH': 30, 'ITA': 20},
    '代案 NDX40/SMH30/ITA30': {'QQQM': 40, 'SMH': 30, 'ITA': 30},
    'NDX40/SMH30/ITA20/インド10': {'QQQM': 40, 'SMH': 30, 'ITA': 20, 'EPI_LONG': 10},
    'ユーザー案 NDX20/SMH50/ITA20/XLE10': {'QQQM': 20, 'SMH': 50, 'ITA': 20, 'XLE': 10},
    '事前登録の答え SMH60/インド20/ITA10/XLE10': {'SMH': 60, 'EPI_LONG': 20, 'ITA': 10, 'XLE': 10},
    'NASDAQ100だけ': {'QQQM': 100},
    '半導体（SMH）だけ': {'SMH': 100},
    'S&P500（VOO）': {'VOO': 100},
}
LUMP = [('2000-09〜（ITバブル崩壊の途中から・26年）', 200009), ('2006-06〜（ITA が実物・20年）', 200606),
        ('2008-03〜（インドも実物・18.6年）', 200803), ('直近15年 2011-10〜', 201110), ('直近10年 2016-10〜', 201610),
        ('直近5年 2021-10〜', 202110), ('直近1年 2025-10〜', 202510)]
END = 202609
IFREE_EXTRA = 0.00495 - 0.0015     # iFreeNEXT（税込0.495%）と QQQM（0.15%）の費用の差


def months(a, b):
    out, y, m = [], a // 100, a % 100
    while y * 100 + m <= b:
        out.append(y * 100 + m)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def irr_monthly(rets):
    """毎月の初めに1ずつ入れ、最後の月の終わりで評価 → 年率の内部収益率（二分法）"""
    W = 0.0
    for r in rets:
        W = (W + 1) * (1 + r)
    n = len(rets)

    def fv(g):  # 月率 g で同じ入金を複利したときの最終額
        x = 1 + g
        return sum(x ** (n - t) for t in range(n))
    lo, hi = -0.2, 0.2
    for _ in range(80):
        mid = (lo + hi) / 2
        if fv(mid) < W:
            lo = mid
        else:
            hi = mid
    return (1 + (lo + hi) / 2) ** 12 - 1, W / n


def stats(rets):
    g, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        g *= 1 + r
        peak = max(peak, g)
        mdd = min(mdd, g / peak - 1)
    mu = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets)) * math.sqrt(12)
    return dict(cagr=g ** (12 / len(rets)) - 1, vol=sd, mdd=mdd)


def main():
    import bestpf_ext as X
    import bestpf_tech12 as T12
    res = X.rank_result()
    rows, chains = res['rows'], res['chains']
    fx = T12.fx_month_end()
    allm = months(200009, END)
    fxr = {}
    prev = None
    for m in months(200008, END):
        if prev is not None:
            fxr[m] = fx[m] / fx[prev] - 1
        prev = m

    def series(wd, ccy, ifree=False):
        tot = sum(wd.values())
        w = {c: v / tot for c, v in wd.items()}
        out = {}
        for m in allm:
            r = sum(w[c] * (chains[c][m] + (rows[c]['A1'] - rows[c]['A1_gross']) / 12) for c in w)
            if ifree:
                r -= w.get('QQQM', 0) * IFREE_EXTRA / 12
            if ccy == 'JPY':
                r = (1 + r) * (1 + fxr[m]) - 1
            out[m] = r
        return out

    doc = dict(generated=datetime.date.today().isoformat(), tool='night/bestpf_realized.py', posthoc=True, end=END,
               ports={k: v for k, v in PORTS.items()}, results={})
    for nm, wd in PORTS.items():
        r = {}
        for ccy in ('USD', 'JPY'):
            s = series(wd, ccy)
            lump = {lab: round(100 * stats([s[m] for m in months(a, END)])['cagr'], 2) for lab, a in LUMP}
            st = stats([s[m] for m in allm])
            dca_end = {}
            for yrs in (20, 15, 10, 5):
                a = months(200009, END)[-12 * yrs]
                irr, mult = irr_monthly([s[m] for m in months(a, END)])
                dca_end[f'{yrs}年（{a // 100}-{a % 100:02d}〜）'] = dict(irr=round(100 * irr, 2), 倍率=round(mult, 2))
            roll = {}
            for yrs in (20, 15):
                n = 12 * yrs
                v = [irr_monthly([s[m] for m in allm[i:i + n]])[0] for i in range(len(allm) - n + 1)]
                vs = sorted(v)
                roll[f'{yrs}年'] = dict(窓の数=len(v), 最小=round(100 * vs[0], 2), 中央=round(100 * vs[len(vs) // 2], 2),
                                       最大=round(100 * vs[-1], 2), 以上15=round(100 * sum(x >= 0.15 for x in v) / len(v), 1),
                                       以上10=round(100 * sum(x >= 0.10 for x in v) / len(v), 1),
                                       最小の窓=f'{allm[v.index(vs[0])] // 100}-{allm[v.index(vs[0])] % 100:02d}〜')
            r[ccy] = dict(一括の年率=lump, ぶれ=round(100 * st['vol'], 1), 最大下落=round(100 * st['mdd'], 1),
                          今日で終わる積立=dca_end, 転がる積立=roll)
        if 'QQQM' in wd:
            s = series(wd, 'JPY', ifree=True)
            a = months(200009, END)[-240]
            r['JPY_iFreeNEXT'] = dict(一括の年率_2000_09=round(100 * stats([s[m] for m in allm])['cagr'], 2),
                                      積立20年_irr=round(100 * irr_monthly([s[m] for m in months(a, END)])[0], 2))
        doc['results'][nm] = r
        u, j = r['USD'], r['JPY']
        print(f"== {nm}")
        print('   一括 ドル', u['一括の年率'])
        print('   一括 円  ', j['一括の年率'])
        print(f"   ぶれ {u['ぶれ']}%（円 {j['ぶれ']}）・最大下落 {u['最大下落']}%（円 {j['最大下落']}）")
        print('   今日で終わる積立 ドル', {k: v['irr'] for k, v in u['今日で終わる積立'].items()}, '円', {k: v['irr'] for k, v in j['今日で終わる積立'].items()})
        print('   転がる積立 ドル', u['転がる積立'], '\n              円  ', j['転がる積立'])
        if 'JPY_iFreeNEXT' in r:
            print('   iFreeNEXT で持つと（円）', r['JPY_iFreeNEXT'])
    doc['warn'] = ['2000〜2026 という一つの歴史（テックと半導体が勝った時代）・窓は重なっていて独立でない',
                   'ITA は 2006-05 まで FSDAX（能動の投信）・インドは 2008-02 まで JKP の代理・NASDAQ100 は QQQ→QQQM',
                   '毎月の組み直しを仮定（本物は不足から買う・売らない）・税は NISA を仮定（配当の外国税だけ引く）',
                   '過去の実績であって予想ではない。予想（5つの世界の平均）は bestpf_check の積立20年の内部収益率（中央で10〜11%）']
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)


if __name__ == '__main__':
    main()
