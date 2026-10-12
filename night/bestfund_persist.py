#!/usr/bin/env python3
"""night/bestfund_persist.py — 『過去の一番は次も一番か』を測る（bestfund の H4・読むだけ・門には触れない）

事前登録 out/bestfund_prereg.json（d5eab7f）の historical_tests.H4_walk_forward_persistence どおり。
毎年12月末に、過去 L 年の年率の上乗せ（市場・平均との差）と、次の H 年の年率の上乗せを作り、
  - 日付ごとに平均を引いた（固定効果）横断の傾き β（次の上乗せ ÷ 過去の上乗せ）
  - 順位の相関（日付ごとのスピアマンの平均）
  - 過去の1位・上位5の次の H 年の上乗せ（平均）と、市場・平均に勝った割合
を出す。L ∈ {10,15,20}・H ∈ {10,20}。重なりの無い日付（H 年ごと）の結果も並べる。
単位: (1) French 49業種（時価総額加重・1926〜・相手は French の市場）
      (2) French の型（規模×簿価時価比・規模×収益性・規模×過去12か月の各 2×3＝18本・相手は市場）
      (3) French の国別（ドル建て・1975〜・相手は20か国の等分）
      (4) この調査の賭けのつなぎ（2000〜・生き残りだけ・参考）
世界 E の λ ＝ L=20・H=20 の傾き β を (1)(2)(3) で別々に出した単純平均（0未満は0・1超は1）。

上乗せは『幾何の年率の差』（etf_forward_rank の X と同じ物差し）。窓の中に欠けた月がある単位はその日付から外す（0と読まない）。

  python3 night/bestfund_persist.py   → out/bestfund_persist.json
"""
import datetime, json, math, os, statistics as S, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import mw_common as M          # noqa: E402
import gaps_common as G        # noqa: E402
import bestfund_data as D      # noqa: E402

OUT = os.path.join(BASE, 'out', 'bestfund_persist.json')
GRID_L, GRID_H = (10, 15, 20), (10, 20)


def months_of_year_span(y0, y1):
    """y0 年1月〜y1 年12月の yyyymm の list"""
    return [y * 100 + m for y in range(y0, y1 + 1) for m in range(1, 13)]


def ann(r, ks):
    if not ks or any(k not in r for k in ks):
        return None
    return math.exp(math.fsum(math.log1p(r[k]) for k in ks) * 12 / len(ks)) - 1


def spearman(a, b):
    def rk(x):
        o = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and x[o[j + 1]] == x[o[i]]:
                j += 1
            for t in range(i, j + 1):
                r[o[t]] = (i + j) / 2
            i = j + 1
        return r
    if len(a) < 3:
        return None
    return M.corr(rk(a), rk(b))


def panel(units, bench, L, H, bench_is_mean=False):
    """units: {名前: {yyyymm: r}}・bench: {yyyymm: r}（bench_is_mean=True なら、その日の単位の等分を相手にする）
    → 日付ごとの [(名前, 過去の上乗せ, 次の上乗せ)]"""
    allm = sorted(set().union(*[set(u) for u in units.values()]))
    y_first, y_last = allm[0] // 100, allm[-1] // 100
    if allm[-1] % 100 != 12:
        y_last -= 1                         # 最後の年が12月まで無ければ使わない
    if allm[0] % 100 != 1:
        y_first += 1
    out = {}
    for y in range(y_first + L - 1, y_last - H + 1):
        past, fut = months_of_year_span(y - L + 1, y), months_of_year_span(y + 1, y + H)
        rows = []
        if bench_is_mean:
            ok = [n for n, u in units.items() if all(k in u for k in past) and all(k in u for k in fut)]
            if len(ok) < 5:
                continue
            bm = {k: S.mean(units[n][k] for n in ok) for k in past + fut}
        else:
            if any(k not in bench for k in past + fut):
                continue
            bm = bench
            ok = [n for n, u in units.items() if all(k in u for k in past) and all(k in u for k in fut)]
        gp, gf = ann(bm, past), ann(bm, fut)
        for n in ok:
            rows.append((n, ann(units[n], past) - gp, ann(units[n], fut) - gf))
        if len(rows) >= 5:
            out[y] = rows
    return out


def summarize(pan, H, non_overlap=False):
    dates = sorted(pan)
    if non_overlap and dates:
        d0 = dates[0]
        dates = [d for d in dates if (d - d0) % H == 0]
    if not dates:
        return None
    xs, ys, rhos, top1, top5, top1_win, top5_win = [], [], [], [], [], [], []
    for d in dates:
        rows = pan[d]
        mx, my = S.mean(r[1] for r in rows), S.mean(r[2] for r in rows)
        for _, x, y in rows:
            xs.append(x - mx)
            ys.append(y - my)
        rho = spearman([r[1] for r in rows], [r[2] for r in rows])
        if rho is not None:
            rhos.append(rho)
        srt = sorted(rows, key=lambda r: -r[1])
        top1.append(srt[0][2])
        top1_win.append(1 if srt[0][2] > 0 else 0)
        t5 = srt[:5]
        top5.append(S.mean(r[2] for r in t5))
        top5_win.append(S.mean(1 if r[2] > 0 else 0 for r in t5))
    sxx = sum(x * x for x in xs)
    beta = sum(x * y for x, y in zip(xs, ys)) / sxx if sxx else None
    return {'dates': len(dates), 'first': dates[0], 'last': dates[-1], 'units_per_date': round(S.mean(len(pan[d]) for d in dates), 1),
            'beta': None if beta is None else round(beta, 3),
            'rank_corr_mean': round(S.mean(rhos), 3) if rhos else None,
            'top1_next_excess_pct': round(100 * S.mean(top1), 2), 'top1_win_share': round(S.mean(top1_win), 3),
            'top5_next_excess_pct': round(100 * S.mean(top5), 2), 'top5_win_share': round(S.mean(top5_win), 3)}


def units_industry():
    ret, _, _ = D.ind49()
    return {n: {k: v / 100 for k, v in s.items() if v > -99} for n, s in ret.items()}, D.french_mkt()


def units_style():
    out = {}
    for ds, cols in (('6_Portfolios_2x3', ['SMALL LoBM', 'ME1 BM2', 'SMALL HiBM', 'BIG LoBM', 'ME2 BM2', 'BIG HiBM']),
                     ('6_Portfolios_ME_OP_2x3', ['SMALL LoOP', 'ME1 OP2', 'SMALL HiOP', 'BIG LoOP', 'ME2 OP2', 'BIG HiOP']),
                     ('6_Portfolios_ME_Prior_12_2', ['SMALL LoPRIOR', 'ME1 PRIOR2', 'SMALL HiPRIOR', 'BIG LoPRIOR', 'ME2 PRIOR2', 'BIG HiPRIOR'])):
        ser = M.french_series(ds, want='Average Value Weighted Returns')
        for c in cols:
            out[f'{ds}:{c}'] = ser[c]
    return out, D.french_mkt()


def units_country():
    return {c: G.french_country(c, 'Dollar') for c in D.DEV20}


def units_bets():
    ch = D.chains()
    out = {}
    for b, d in ch.items():
        s = {k: v for k, v in d['usd'].items() if k >= 200001}
        if b in D.JPY_NATIVE:
            s = {k: v for k, v in d['usd'].items() if k >= 200001}
        if len(s) >= 240:
            out[b] = s
    return out, ch['SP500']['usd']


def run():
    ind, mkt = units_industry()
    sty, mkt2 = units_style()
    cty = units_country()
    bets, spx = units_bets()
    res = {'generated': datetime.date.today().isoformat(), 'tool': 'night/bestfund_persist.py',
           'prereg': 'out/bestfund_prereg.json（d5eab7f）historical_tests.H4', 'grid': {}}
    for L in GRID_L:
        for H in GRID_H:
            key = f'L{L}_H{H}'
            e = {}
            for nm, (units, bench, mean_b) in {'industry': (ind, mkt, False), 'style': (sty, mkt2, False),
                                               'country': (cty, None, True)}.items():
                pan = panel(units, bench, L, H, bench_is_mean=mean_b)
                e[nm] = {'overlapping': summarize(pan, H), 'non_overlapping': summarize(pan, H, non_overlap=True)}
            if L + H <= 26:
                pan = panel(bets, spx, L, H)
                e['bets_2000_reference'] = {'overlapping': summarize(pan, H), 'non_overlapping': summarize(pan, H, non_overlap=True)}
            res['grid'][key] = e
    lam = {}
    for nm in ('industry', 'style', 'country'):
        b = res['grid']['L20_H20'][nm]['overlapping']
        lam[nm] = None if not b else b['beta']
    vals = [v for v in lam.values() if v is not None]
    raw = S.mean(vals) if vals else None
    res['lambda_main'] = {'by_unit': lam, 'mean_raw': None if raw is None else round(raw, 3),
                          'lambda': None if raw is None else round(min(1.0, max(0.0, raw)), 3),
                          'rule': 'L=20・H=20 の傾き β（重なりあり）を業種・型・国で別々に出して単純平均。0未満は0・1超は1（事前登録）'}
    lam10 = {}
    for nm in ('industry', 'style', 'country'):
        b = res['grid']['L10_H10'][nm]['overlapping']
        lam10[nm] = None if not b else b['beta']
    v10 = [v for v in lam10.values() if v is not None]
    r10 = S.mean(v10) if v10 else None
    res['lambda_L10_H10'] = {'by_unit': lam10, 'mean_raw': None if r10 is None else round(r10, 3),
                             'lambda': None if r10 is None else round(min(1.0, max(0.0, r10)), 3), 'rule': '感度「λ を L=10・H=10 から」'}
    res['⚠'] = ['重なりのある日付は互いに独立でない（点の推定だけ・検定はしない）',
                '業種の中には社数の少ない時期がある（事前登録どおり除外していない）',
                '国は1975〜（French の国別のファイルは2025-12まで）。賭けのつなぎは2000〜・生き残りだけ（参考）']
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
    return res


def main():
    res = run()
    print('→', OUT)
    for key, e in res['grid'].items():
        for nm, v in e.items():
            o, n = v['overlapping'], v['non_overlapping']
            if not o:
                print(f'{key} {nm}: なし')
                continue
            print(f"{key} {nm:20} β={o['beta']:+.3f} ρ={o['rank_corr_mean']:+.3f} 1位の次{o['top1_next_excess_pct']:+.2f}%（勝ち{o['top1_win_share']:.0%}） "
                  f"上位5の次{o['top5_next_excess_pct']:+.2f}%（勝ち{o['top5_win_share']:.0%}） 日付{o['dates']}({o['first']}〜{o['last']}) "
                  f"| 重なりなし β={n['beta'] if n else None} 日付{n['dates'] if n else 0}")
    print('λ（主）', res['lambda_main'])
    print('λ（L10H10）', res['lambda_L10_H10'])


if __name__ == '__main__':
    main()
