#!/usr/bin/env python3
"""night/edge/fam_dip_lever.py — 系統 dip_lever（第1回）: 大きく下げた後だけ借りる

規則（凍結する spec の形）:
  ・市場の配当込み指数（月末の値を累積したもの）が m−1 月末に「それまでの最高値（m−1 月末までの月末値の最大）」から
    X 以上下にあるとき、月 m の持ち高を 1＋e にする。そうでないときは 1（ふつうに市場を持つ）。
  ・降り方（exit）:
      'below'   … m−1 月末の下落が X 以上のあいだだけ借りる（戻れば降りる・また割れば乗る）
      'newhigh' … 一度 X 以上下げたら、配当込み指数が最高値を更新する（下落 0）まで借り続ける
      'N'       … 一度 X 以上下げたら N か月借りる。ただし その前に最高値を更新したらそこで降りる
                  （同じ下落の山では一度しか乗らない。次に乗れるのは最高値を更新した後）
  ・借りる費用: 借りた分 e に 短期金利＋0.4%/年、経費 0.9%/年（借りた分にだけ＝2倍ETFを e の割合で持つのと同じ）。
    米国は毎日リセット（French の日次）。他の市場は日次が無いので月次で借り直す（近似・concerns に記す）。
  ・費用: 持ち高の変化 1 あたり 0.10%（turnover＝|L_m − L_{m−1}|）。

先読みの無さ: 月 m の持ち高は ret の m−1 月までの累積だけで決まる（dd_lever の中で、月 m のリターンは持ち高を決めた後に足す）。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h

FAMILY = {
    'key': 'dip_lever',
    'name': '大きく下げた後だけ借りる（下落時レバレッジ）',
    'implement': ('ふだんは 米国株全体／S&P500 の1倍（VTI・eMAXIS Slim 米国株式 など）を持つ。米国株の配当込み指数が月末に'
                  '過去の最高値から X% 以上下にあれば、翌月の頭に持ち高を 1＋e 倍へ上げる: 楽天証券の課税口座で 1倍の一部（e の割合）を'
                  '売り、同じ額で 2倍・毎日リセットの ETF（SSO 経費0.87%／SPUU 0.60%、または 投信の iFreeレバレッジ S&P500）を買う'
                  '（e=1 なら全部を 2倍ETF に）。条件が外れたら元の1倍に戻す。⚠ レバレッジ型は NISA の対象外＝課税口座で持つ'
                  '（入れ替える部分は NISA の外に置いておく必要がある）。信号は月1回、月末の指数だけで決まる'),
}

SPREAD, FEE, COST = 0.004, 0.009, 0.001


# ───────────────────────── 信号（先読みなし） ─────────────────────────
def dd_lever(ret, X, e, exit='below', N=None):
    """ret: {YYYYMM: 月次リターン}。→ {YYYYMM: 月 m の持ち高 L_m}。
    L_m は m−1 月末までの累積（v）とその最大（peak）だけで決める。月 m のリターンは L_m を決めた後に v へ足す。
    月が飛んでいたら（欠測）そこで指数を切らずに続ける（欠測月は持ち高を決めない）"""
    lev = {}
    v = peak = 1.0
    on = False          # 'newhigh' / 'N' の乗っている状態
    armed = True        # この下落の山でまだ乗っていない
    start_i = 0
    i = 0
    for m in sorted(ret):
        dd = v / peak - 1.0                     # m−1 月末の下落（初月は 0）
        if exit == 'below':
            state = dd <= -X
        else:
            if dd >= 0:                          # 最高値を更新した（戻った）→ 降りて、次の山に備える
                on, armed = False, True
            if (not on) and armed and dd <= -X:
                on, armed, start_i = True, False, i
            if on and exit == 'N' and i - start_i >= N:
                on = False
            state = on
        lev[m] = 1.0 + e if state else 1.0
        v *= 1.0 + ret[m]
        peak = max(peak, v)
        i += 1
    return lev


def turnover_of(lev):
    ms = sorted(lev)
    tv = {ms[0]: 0.0} if ms else {}
    for a, b in zip(ms, ms[1:]):
        tv[b] = abs(lev[b] - lev[a])
    return tv


# ───────────────────────── 持ち高 → リターン ─────────────────────────
def apply_daily(bench_m, lev, daily, drf):
    """米国: 借りた月だけ、日次で毎日リセットの L 倍を作る。French の月次と日次の複利はわずかにずれるので、
    借りた月の規則のリターン = 月次の市場 + (日次で作った L 倍の月の複利 − 日次で作った 1倍の月の複利)。
    こうすると 1倍の月は相手と1ビットも違わず、借りた月は 借入・経費・毎日リセットの減価だけが差として入る。
    日次が無い月は月次で借り直す近似へ落とす"""
    by_m = {}
    for k in daily:
        by_m.setdefault(k // 100, []).append(k)
    out = {}
    for m, r in bench_m.items():
        L = lev.get(m, 1.0)
        if L == 1.0:
            out[m] = r
            continue
        days = by_m.get(m)
        if days:
            e = L - 1.0
            one = {k: daily[k] for k in days}
            lv = h.lev_daily(one, {k: drf.get(k, 0.0) for k in days}, L, spread=SPREAD, fee=FEE * e)
            g1 = 1.0
            gL = 1.0
            for k in sorted(days):
                g1 *= 1 + one[k]
                gL *= 1 + lv[k]
            out[m] = r + (gL - g1)
        else:
            out[m] = None
    return out


def apply_monthly(bench_m, lev, rf):
    """日次の無い市場: 月次で借り直す L 倍（借りた分 e に rf＋0.4%/年、経費 0.9%/年×e）"""
    out = {}
    for m, r in bench_m.items():
        L = lev.get(m, 1.0)
        e = L - 1.0
        if e == 0:
            out[m] = r
        else:
            f = rf.get(m)
            if f is None:
                continue
            out[m] = L * r - e * (f + SPREAD / 12) - e * FEE / 12
    return out


def _other_markets(spec, us_rf):
    """同じ凍結した規則を、その市場自身の配当込み指数（米ドル建て）に当てる。現金・借入は米国の短期金利"""
    X, e, ex, N = spec['X'], spec['e'], spec['exit'], spec.get('N')
    mk = {}
    for nm, s in sorted(h.french_countries('Dollar').items()):
        s = {m: v for m, v in s.items() if m in us_rf}
        if len(s) < 24:
            continue
        lev = dd_lever(s, X, e, ex, N)
        r = apply_monthly(s, lev, us_rf)
        mk[f'国:{nm}'] = {'ret': r, 'bench': s, 'rf': us_rf, 'turnover': turnover_of(lev), 'cost': COST}
    # 地域: 国と重ならないもの（Japan は 国:Japan と同じ市場なので外す）。North_America・Developed は米国が大半＝米国の再演なので外す
    regions = ['Developed_ex_US', 'Europe', 'Asia_Pacific_ex_Japan']
    for rg in regions:
        try:
            s, rrf = h.french_region(rg)
        except Exception:
            continue
        s = {m: v for m, v in s.items() if m in us_rf}
        if len(s) < 24:
            continue
        lev = dd_lever(s, X, e, ex, N)
        mk[f'地域:{rg}'] = {'ret': apply_monthly(s, lev, us_rf), 'bench': s, 'rf': us_rf,
                            'turnover': turnover_of(lev), 'cost': COST}
    try:                                                  # 新興国は 3因子の表が無く 5因子の表にある（同じ Mkt-RF＋RF・米ドル）
        d = h.french('Emerging_5_Factors')
        t = next(iter(d))
        s = {m: (d[t]['Mkt-RF'][m] + d[t]['RF'][m]) / 100 for m in d[t]['Mkt-RF'] if m in d[t]['RF'] and 99999 < m < 1000000}
        s = {m: v for m, v in s.items() if m in us_rf}
        if len(s) >= 24:
            lev = dd_lever(s, X, e, ex, N)
            mk['地域:Emerging'] = {'ret': apply_monthly(s, lev, us_rf), 'bench': s, 'rf': us_rf,
                                   'turnover': turnover_of(lev), 'cost': COST}
    except Exception:
        pass
    return mk


def run(spec):
    X, e, ex, N = spec['X'], spec['e'], spec['exit'], spec.get('N')
    mkt, rf = h.us_market()
    daily, drf = h.us_market_daily()
    lev = dd_lever(mkt, X, e, ex, N)
    r = apply_daily(mkt, lev, daily, drf)
    miss = [m for m, v in r.items() if v is None]
    if miss:                                               # 日次が欠けた月は月次の借り直しで埋める
        mr = apply_monthly({m: mkt[m] for m in miss}, lev, rf)
        for m in miss:
            if m in mr:
                r[m] = mr[m]
            else:
                del r[m]
    out = {'ret': r, 'bench': mkt, 'rf': rf, 'turnover': turnover_of(lev), 'cost': COST, 'lev': lev,
           'markets': _other_markets(spec, rf) if spec.get('replicate', True) else {}}
    return out


if __name__ == '__main__':
    import json
    sp = json.load(open(os.path.join(h.BASE, 'out', 'edge', 'spec_dip_lever.json')))['spec']
    x = run(sp)
    print(json.dumps(h.stats(x['ret'], x['bench'], x['rf'], turnover=x['turnover'], cost=x['cost']), ensure_ascii=False))
