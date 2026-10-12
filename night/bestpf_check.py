#!/usr/bin/env python3
"""night/bestpf_check.py — 好きな配合を bestpf と同じ物差しで1本ずつ測る（2026-10-12・ユーザー「NDX50/SMH25/ITA10/個別15の確率は？」）

読むだけ。門・採点・配分には触れない。物差しは night/bestpf_eval.py・bestpf_smh_timing.py と同じ
（5つの世界 A1・A2・B・C・D／重み π は R8／20年の毎月の積立の内部収益率の表）。個別株は外側（ETF 側だけを正規化して測る）。
窓は2つ: 崩れあり（A1 と共分散 2000-09〜）／ドットコム級なし（2002-11〜）。

使い方: python3 night/bestpf_check.py '名前=QQQM:50,SMH:25,ITA:10' '今=QQQM:50,SMH:20,ITA:15' ...
  （QQQM＝NASDAQ100〔iFreeNEXT と同じ指数〕。数字は合計の比でよい＝ETF 側へ正規化する）
出力: out/bestpf_check.json（最後に測った分で上書き）
"""
import datetime, json, math, os, sys
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etf_forward_rank as R      # noqa: E402
import etf_forward_combo as CB    # noqa: E402
import etf_p15 as P               # noqa: E402
import bestpf_eval as E           # noqa: E402
import bestpf_ext as X            # noqa: E402

OUT = os.path.join(BASE, 'out', 'bestpf_check.json')
WORLDS = E.WORLDS
WINDOWS = {'崩れあり 2000-09〜': (200009, 202609), 'ドットコム級なし 2002-11〜': (200211, 202609)}
CRASH00, CRASH22 = (200009, 200210), (202112, 202209)


def parse(args):
    out = {}
    for a in args:
        nm, spec = a.split('=', 1)
        out[nm] = {k: float(v) for k, v in (x.split(':') for x in spec.split(','))}
    return out


TECH12_JSON = os.path.join(BASE, 'out', 'bestpf_tech12.json')
# 超大型株の基礎率（tech_persist: 時価総額の最大の1割が過去10年に市場に勝った後、次の10年は中央 −1.2%/年・24窓中3勝）。
# 感度でだけ使う: 世界 B・C・D から 1.2pt×（米国の時価総額上位10社の保有比率）を引く。上位10社は 2026-09 の組み直しの時価総額の順
MEGA10 = {'NVDA', 'AAPL', 'GOOGL', 'GOOG', 'MSFT', 'AMZN', 'SPCX', 'META', 'AVGO', 'TSLA', 'BRK.B', 'BRK-B'}
MEGA_PEN = 0.012


def add_tech12(res):
    """楽天・テック12 を TECH12 として足す（night/bestpf_tech12.py の組み直し）。2010-01 より前は NASDAQ-100（QQQ の総額＝費用を足し戻す）で埋める"""
    j = json.load(open(TECH12_JSON))
    rows, chains = res['rows'], res['chains']
    q = rows['QQQM']
    tm = {int(k): v for k, v in j['monthly_usd'].items()}
    ch = {}
    for m, v in chains['QQQM'].items():
        ch[m] = tm[m] if m in tm else v + q['er_data'] / 12
    chains['TECH12'] = ch
    w = j['worlds']
    rows['TECH12'] = dict(ja='楽天・テック12', A1_gross=0.0, A1=-(w['fee'] + w['tax_drag']), B=w['B'], C=w['C'], D_override=w['D'],
                          er_vehicle=w['fee'], tax_drag=w['tax_drag'], tech12_from=min(tm), holdings=w['holdings'])
    return j


def mega_share(c, rows):
    if c == 'TECH12':
        h = rows['TECH12']['holdings']
    else:
        prof_old = json.load(open(os.path.join(BASE, 'out', 'etf_profiles.json'))).get('etfs') or {}
        p_new = os.path.join(BASE, 'out', 'etf_forward_profiles.json')
        prof_new = (json.load(open(p_new)).get('etfs') or {}) if os.path.exists(p_new) else {}
        h = R.holdings_of(c, prof_old, prof_new) or (R.holdings_of('QQQ', prof_old, prof_new) if c == 'QQQM' else [])
        if c == 'VOO' and not h:
            return 0.33
    tot = sum(x[1] for x in h)
    return sum(x[1] for x in h if x[0].upper() in MEGA10) / tot if tot else 0.0


def main():
    ports = parse(sys.argv[1:]) or {'今': {'QQQM': 50, 'SMH': 20, 'ITA': 15}}
    res = X.rank_result()
    rows, chains = res['rows'], res['chains']
    assets = sorted({a for w in ports.values() for a in w} | {'VOO'})
    if 'TECH12' in assets:
        add_tech12(res)
    k2 = R.months(*R.A2)
    G2 = np.array([[chains[c][m] for m in k2] for c in assets])
    adj = np.array([rows[c]['A1'] - rows[c]['A1_gross'] for c in assets])
    Dmap, _, _ = E.load_D(rows, assets)
    for c in assets:
        if 'D_override' in rows[c]:
            Dmap[c] = rows[c]['D_override']
    mega = np.array([mega_share(c, rows) for c in assets])
    print('超大型10社の保有比率', {c: round(float(v), 2) for c, v in zip(assets, mega)})
    pi, _, _ = E.load_pi()
    noA2 = {k: (0.0 if k == 'A2' else v) for k, v in pi.items()}
    gB = np.array([rows[c]['B'] for c in assets]); gC = np.array([rows[c]['C'] for c in assets]); gD = np.array([Dmap[c] for c in assets])
    tabs = P.dca_tables(20, [0.0, 0.05, 0.10, 0.15], log=False)
    sim = E.simulate_tables()
    T = 240
    out = {}
    for wname, (a, b) in WINDOWS.items():
        k1 = R.months(a, b)
        G1 = np.array([[chains[c][m] for m in k1] for c in assets])
        S1 = np.cov(np.log1p(G1), bias=True) * 12
        s1 = np.diag(S1).copy()

        def pr(wv, sig, tau, p):
            tot = 0.0
            for k in WORLDS:
                if p.get(k, 0) <= 0:
                    continue
                v = float(P.interp(tabs[tau], np.array([math.log1p(wv[k])]), np.array([sig]))[0])
                tot += p[k] * (v if tau >= 0.10 else 1 - v)
            return tot / sum(p[k] for k in WORLDS if p.get(k, 0) > 0)

        def placed(w, mB, crash, at):
            rets = [math.expm1(mB)] * T
            for t, m in enumerate(R.months(*crash)):
                rets[at + t] = float(w @ np.array([chains[c][m] for c in assets]))
            Wt = 0.0
            for x in rets:
                Wt = (Wt + 1) * (1 + x)
            return float(np.interp(Wt, sim['K'], sim['r_grid']))

        tab = {}
        for nm, wd in ports.items():
            tot = sum(wd.values())
            w = np.array([wd.get(c, 0) / tot for c in assets])
            ps = CB.path_stats((w @ G1)[None, :], len(k1))
            a2 = float(np.expm1(np.log1p(w @ G2).sum() * 12 / len(k2)))
            q = float(w @ S1 @ w); bonus = 0.5 * (float(w @ s1) - q); sig = math.sqrt(q)
            wv = dict(A1=float(ps[0][0]) + float(w @ adj), A2=a2 + float(w @ adj), B=math.expm1(float(w @ np.log1p(gB)) + bonus),
                      C=math.expm1(float(w @ np.log1p(gC)) + bonus), D=math.expm1(float(w @ np.log1p(gD)) + bonus))
            mB = math.log1p(wv['B']) / 12
            hs = P.hist_success(w[None, :], G1, adj, len(k1), tau=0.15)
            pen = MEGA_PEN * float(w @ mega)
            wv_m = dict(wv, B=wv['B'] - pen, C=wv['C'] - pen, D=wv['D'] - pen)
            tab[nm] = {'ETF側の比': {k: round(100 * v / tot, 1) for k, v in wd.items()},
                       'P15π': round(100 * pr(wv, sig, 0.15, pi), 1), 'P15π（A2を外す）': round(100 * pr(wv, sig, 0.15, noA2), 1),
                       'P10π': round(100 * pr(wv, sig, 0.10, pi), 1), 'P5π（5%未満）': round(100 * pr(wv, sig, 0.05, pi), 1),
                       'P0π（元本割れ）': round(100 * pr(wv, sig, 0.0, pi), 1),
                       '世界ごとの年率': {k: round(100 * v, 2) for k, v in wv.items()}, '最悪の世界': round(100 * min(wv.values()), 2),
                       'ぶれ': round(100 * float(ps[1][0]), 1), '最大下落': round(100 * float(ps[2][0]), 1),
                       '積立20年の内部収益率': E.irr_quantiles(sim, {k: math.log1p(v) for k, v in wv.items()}, sig, pi),
                       '崩れ2000型_1〜3年目': round(100 * placed(w, mB, CRASH00, 0), 2), '崩れ2000型_16〜18年目': round(100 * placed(w, mB, CRASH00, 180), 2),
                       '下落2022型_16年目': round(100 * placed(w, mB, CRASH22, 180), 2),
                       '過去の転がる20年で15%以上': round(100 * float(hs[240][0]), 1),
                       '超大型株の比率（ETF側）': round(100 * float(w @ mega), 1),
                       'P15π（超大型株の基礎率で B・C・D を割り引く）': round(100 * pr(wv_m, sig, 0.15, pi), 1),
                       'P5π（同）': round(100 * pr(wv_m, sig, 0.05, pi), 1)}
            r = tab[nm]
            print(f"[{wname}] {nm[:30]:<30} P15π {r['P15π']:5.1f}（A2抜き {r['P15π（A2を外す）']:4.1f}） P10 {r['P10π']:4.1f} P5 {r['P5π（5%未満）']:4.1f} P0 {r['P0π（元本割れ）']:4.1f} "
                  f"最悪 {r['最悪の世界']:5.2f} 下落 {r['最大下落']:6.1f} 崩れ前 {r['崩れ2000型_1〜3年目']:5.2f} 後 {r['崩れ2000型_16〜18年目']:5.2f} 22型後 {r['下落2022型_16年目']:5.2f} "
                  f"過去20年 {r['過去の転がる20年で15%以上']:5.1f} 超大型 {r['超大型株の比率（ETF側）']:4.1f}%→P15 {r['P15π（超大型株の基礎率で B・C・D を割り引く）']:4.1f} IRR中央 {r['積立20年の内部収益率']['50%点']}（10%点 {r['積立20年の内部収益率']['10%点']}・90%点 {r['積立20年の内部収益率']['90%点']}）", flush=True)
        out[wname] = tab
    json.dump(dict(generated=datetime.date.today().isoformat(), tool='night/bestpf_check.py', posthoc=True, pi=pi, results=out,
                   note='ETF 側だけを測る（個別株は外側）。事前登録の外の比較'), open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)


if __name__ == '__main__':
    main()
