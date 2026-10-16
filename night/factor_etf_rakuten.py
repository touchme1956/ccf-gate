#!/usr/bin/env python3
"""night/factor_etf_rakuten.py — 楽天で買える『質・勢い』型の ETF・投資信託（2026-10-16・ユーザー「楽天にqualやMTUMのような優良ETFないの？」・参考・判定なし）

読むだけ。門・採点・配分・注文書には触れない。判定はしない（並べるだけ）。測り方は結果を見る前にこのファイルで固定する。

楽天で買えるか（2026-10-16 の確かめ・道具の中の表 RAKUTEN を写しと突き合わせる）:
  米国 ETF・東証 ETF＝楽天の ETFD.csv（2026-10-16 の写し out/_nx_cache/avuv/ETFD_20261016.csv があれば、A と D の ETF が在り B が無いことを確かめる）
  投資信託＝投資信託協会 投信総合検索ライブラリーの販売会社の欄（2026-10-11 の写し out/_nx_cache/newfunds/jita_full.json があれば、D の投信の販売会社に楽天が居ることを確かめる）
並べる本:
  A 楽天で買える米国 ETF: DGRW（米国の質・配当成長）・MOAT（堀）・QDIV（S&P500 の質・高配当）・VIG（増配）・NOBL（配当貴族）・
    SDVY（中小型の増配）・DGRS（小型の質・配当成長）・IDHQ（米国外の先進国の質）・RSP（S&P500 の均等加重・参考）
  B 楽天に無い（比べるため）: QUAL（米国の質）・MTUM（米国の勢い）・SPHQ（S&P500 の質）・SPMO（S&P500 の勢い）・COWZ（キャッシュフロー）・JQUA（米国の質）
  C 相手: SPY（S&P500）・QQQ（NASDAQ100）
  D 楽天で買える日本の器（記録が短い）: 楽天・ワイド・モート（投信・MOAT と同じ指数）・eMAXIS S&P500クオリティ高配当（投信・QDIV と同じ指数）・
    ニッセイ・S米国連続増配（投信・Solactive US Dividend Elite）・SMT 米国株式モメンタム（投信・能動の決まりで勢いの銘柄を選ぶ）・
    356A（東証・S&P 500 Quality FCF Aristocrats）・2014（東証・Morningstar US Dividend Growth＝DGRO と同じ指数）
系列: 米国 ETF＝Yahoo の調整後終値（配当込み・mw_common.yahoo）の月次・ドル建て。投資信託＝投資信託協会の基準価額の日次 CSV
  （分配金を足して再投資・nx_jpfunds_data.monthly_tr・最後の日を 2026-09-30 にして読む）。東証 ETF＝Yahoo（円）。
  円＝月末の FRED DEXJPUS の比（unx_assets.fred_monthly_last）。最後の月は 2026-09（途中の 2026-10 は入れない）。
出すもの:
  ① 各本の設定来（最初の完全な月〜2026-09）: 年率・ぶれ・最大下落・同じ窓の SPY・QQQ の年率と差（年率の差・pt）
  ② 共通の窓: W1＝2013-11〜2026-09（A・B のうち 2013-10 までにできた本）・W2＝2018-08〜2026-09（A・B の全部）・
     直近10年 2016-10〜・直近5年 2021-10〜・直近3年 2023-10〜（その窓の最初の月から値がある本だけ）
     各本の年率・ぶれ・最大下落・SPY との差・QQQ との差・月次の SPY に対するベータ・QQQ との相関
  ③ 暦年（2014〜2026 の1〜9月）と 2020年2〜3月（コロナの下げ）・2022年（テックの下げ）
  ④ 転がる36か月で SPY を上回った窓の割合と差の中央値（W1 の本・W1 の中）
  ⑤ D の器: 設定来の円の年率（12か月未満は累計だけ）と、同じ月の 双子の米国 ETF（円）・SPY（円）・QQQ（円）
使い方: python3 night/factor_etf_rakuten.py → out/factor_etf_rakuten.json
"""
import csv, datetime, html, io, json, math, os, statistics as S, sys, unicodedata

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import mw_common as M          # noqa: E402
import unx_assets as U         # noqa: E402

OUT = os.path.join(BASE, 'out', 'factor_etf_rakuten.json')
LAST = 202609
ETFD = os.path.join(BASE, 'out', '_nx_cache', 'avuv', 'ETFD_20261016.csv')
JITA = os.path.join(BASE, 'out', '_nx_cache', 'newfunds', 'jita_full.json')

A = {  # 楽天で買える米国 ETF（ETFD.csv 2026-10-16）: 何の型か・経費率（%・ETFD の列5）・設定日（列32）
    'DGRW': ('米国の質・配当成長（WisdomTree）', 0.28, '2013-05-22'),
    'MOAT': ('堀（Morningstar Wide Moat Focus）', 0.46, '2012-04-24'),
    'QDIV': ('S&P500 の質・高配当', 0.20, '2018-07-13'),
    'VIG': ('増配（S&P U.S. Dividend Growers）', 0.05, '2006-04-21'),
    'NOBL': ('S&P500 配当貴族', 0.35, '2013-10-08'),
    'SDVY': ('中小型の増配（Nasdaq）', 0.59, '2017-11-01'),
    'DGRS': ('小型の質・配当成長（WisdomTree）', 0.38, '2013-07-25'),
    'IDHQ': ('米国外の先進国の質（S&P）', 0.29, '2007-06-13'),
    'RSP': ('S&P500 の均等加重（参考）', 0.20, '2003-04-24'),
}
B = {  # 楽天に無い（ETFD.csv 2026-10-16 に行が無い）。経費率は各社の公表値
    'QUAL': ('米国の質（MSCI USA Sector Neutral Quality）', 0.15),
    'MTUM': ('米国の勢い（MSCI USA Momentum）', 0.15),
    'SPHQ': ('S&P500 の質', 0.15),
    'SPMO': ('S&P500 の勢い', 0.13),
    'COWZ': ('米国のフリーキャッシュフロー利回り', 0.49),
    'JQUA': ('米国の質（JPMorgan）', 0.12),
}
CMP = ['SPY', 'QQQ']
D = [  # 楽天で買える日本の器: (名前, 種類, 識別子, 双子の米国 ETF or None, 信託報酬〔税込・%〕, 設定日, 何の型か)
    ('楽天・ワイド・モート', '投信', ('JP90C000QG62', '9I311242'), 'MOAT', 0.55, '2024-02-02', 'MOAT と同じ指数（Morningstar Wide Moat Focus）'),
    ('eMAXIS S&P500クオリティ高配当', '投信', ('JP90C000P4Q1', '03311231'), 'QDIV', 0.33, '2023-01-12', 'QDIV と同じ指数（S&P 500 Quality High Dividend）'),
    ('ニッセイ・S米国連続増配', '投信', ('JP90C000Q9X5', '2931223C'), None, 0.11, '2023-12-18', 'Solactive United States Dividend Elite'),
    ('SMT 米国株式モメンタム', '投信', ('JP90C000SCM7', '6431225C'), 'MTUM', 0.77, '2025-12-16', '能動の決まり（短期・中期・長期の上昇率で銘柄を選ぶ）・MTUM は比べるための近い型'),
    ('グローバルX S&P500 キャッシュフロー・トップ100（356A）', '東証', '356A.T', None, 0.198, '2025-04-14', 'S&P 500 Quality FCF Aristocrats'),
    ('iシェアーズ 米国連続増配株（2014）', '東証', '2014.T', 'DGRO', 0.121, '2024-01-17', 'Morningstar US Dividend Growth（DGRO と同じ指数）'),
]
WINDOWS = {'W1 2013-11〜（2013年までにできた本）': 201311, 'W2 2018-08〜（全部）': 201808,
           '直近10年 2016-10〜': 201610, '直近5年 2021-10〜': 202110, '直近3年 2023-10〜': 202310}


def months(a, b):
    out, y, m = [], a // 100, a % 100
    while y * 100 + m <= b:
        out.append(y * 100 + m)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def first_full_month(date_s):
    y, m, d = (int(x) for x in date_s.split('-'))
    return U.months_add(y * 100 + m, 1)


def cagr(s, ms):
    if not ms or any(m not in s for m in ms):
        return None
    return math.exp(sum(math.log1p(s[m]) for m in ms) * 12 / len(ms)) - 1


def total(s, ms):
    if not ms or any(m not in s for m in ms):
        return None
    return math.prod(1 + s[m] for m in ms) - 1


def vol(s, ms):
    xs = [s[m] for m in ms]
    mu = sum(xs) / len(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs)) * math.sqrt(12)


def mdd(s, ms):
    lvl, peak, worst = 1.0, 1.0, 0.0
    for m in ms:
        lvl *= 1 + s[m]
        peak = max(peak, lvl)
        worst = min(worst, lvl / peak - 1)
    return worst


def beta(s, b, ms):
    xs, ys = [b[m] for m in ms], [s[m] for m in ms]
    mx, my = S.mean(xs), S.mean(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / vx if vx else None


def to_jpy(s, fx):
    out = {}
    for m, v in s.items():
        p = U.months_add(m, -1)
        if m in fx and p in fx:
            out[m] = (1 + v) * fx[m] / fx[p] - 1
    return out


def p2(x, k=2):
    return None if x is None else round(100 * x, k)


def nf(x):
    return unicodedata.normalize('NFKC', x or '')


def check_rakuten():
    """ETFD.csv と投信ライブラリーの写しがあれば、道具の中の表（A・B・D）と食い違わないか確かめる。食い違えば止める"""
    out = {}
    if os.path.exists(ETFD):
        rows = list(csv.reader(io.StringIO(open(ETFD, 'rb').read().decode('utf-8-sig'))))
        us = {r[1]: r for r in rows if len(r) > 32 and r[3] in ('NYSE ARCA', 'ﾅｽﾀﾞｯｸ', 'Cboe')}
        jp = {r[0]: r for r in rows if r[3] == '東証ETF'}
        miss = [t for t in A if t not in us]
        wrong = [t for t in B if t in us]
        jmiss = [x[2] for x in D if x[1] == '東証' and x[2] not in jp]
        assert not miss and not wrong and not jmiss, f'楽天の一覧と食い違う: 無い {miss} {jmiss}・在る {wrong}'
        er = {t: float(us[t][5]) for t in A if us[t][5]}
        bad = {t: (A[t][1], er[t]) for t in er if abs(er[t] - A[t][1]) > 1e-9}
        assert not bad, f'経費率が一覧と違う: {bad}'
        out['ETFD'] = dict(file='out/_nx_cache/avuv/ETFD_20261016.csv（楽天 ETFD.csv の 2026-10-16 の写し）', A_在る=list(A), B_無い=list(B),
                           東証=[x[2] for x in D if x[1] == '東証'], 純資産_百万ドル={t: float(us[t][24]) for t in A if us[t][24]},
                           配当利回り={t: float(us[t][19]) for t in A if us[t][19]})
    else:
        out['ETFD'] = '写しが無い（表 A・B は 2026-10-16 に確かめた値）'
    if os.path.exists(JITA):
        j = json.load(open(JITA))
        by = {r['isinCd']: r for r in j['rows']}
        res = {}
        for name, kind, ident, twin, fee, est, what in D:
            if kind != '投信':
                continue
            r = by.get(ident[0])
            assert r is not None, f'投信ライブラリーに無い: {name}'
            rk = any('楽天' in nf(i.get('instName')) for i in r.get('institutionInfo') or [])
            assert rk, f'楽天の販売会社に無い: {name}'
            res[name] = dict(楽天=rk, NISA成長=r.get('nisaGrowthFlg') == '1', NISAつみたて=r.get('nisaFlg') == '1',
                             信託報酬_税抜=float(r.get('trustReward')), 指数型=r.get('supplementKindCd') == '1')
        out['投信ライブラリー'] = dict(file='out/_nx_cache/newfunds/jita_full.json（2026-10-11 の写し）', funds=res)
    else:
        out['投信ライブラリー'] = '写しが無い（表 D は 2026-10-11 の写しで確かめた値）'
    return out


def nav_monthly(isin, assoc):
    import nx_jpfunds_data as J
    J.CUTOFF = 20260930   # 2026-09 まで読む（既定は 2026-08-31）
    b = J.Lib().csv(isin, assoc)
    daily, bad = J.parse_csv(b)
    return J.monthly_tr(daily), bad, (daily[0][0] if daily else None)


def window_row(s, ser, ms):
    spy, qqq = ser['SPY'], ser['QQQ']
    c, cs, cq = cagr(s, ms), cagr(spy, ms), cagr(qqq, ms)
    return dict(年率=p2(c), ぶれ=p2(vol(s, ms), 1), 最大下落=p2(mdd(s, ms), 1), SPYとの差=p2(c - cs), QQQとの差=p2(c - cq),
                SPYに対するベータ=round(beta(s, spy, ms), 2), QQQとの相関=round(M.corr([s[m] for m in ms], [qqq[m] for m in ms]), 2))


def main():
    rk = check_rakuten()
    tick = list(A) + list(B) + CMP
    ser = {t: {m: v for m, v in M.yahoo(t).items() if m <= LAST} for t in tick}
    for t in tick:
        assert ser[t], f'系列が取れない: {t}'

    # ① 設定来
    since = {}
    for t in list(A) + list(B):
        f = min(ser[t])
        ms = [m for m in months(f, LAST)]
        if any(m not in ser[t] for m in ms):
            ms = [m for m in ms if m in ser[t]]
            gap = True
        else:
            gap = False
        c, cs, cq = cagr(ser[t], ms), cagr(ser['SPY'], ms), cagr(ser['QQQ'], ms)
        since[t] = dict(型=(A.get(t) or B.get(t))[0], 楽天=t in A, 経費率=(A.get(t) or B.get(t))[1], 窓=f'{ms[0]}〜{ms[-1]}', 月数=len(ms),
                        年率=p2(c), ぶれ=p2(vol(ser[t], ms), 1), 最大下落=p2(mdd(ser[t], ms), 1),
                        SPYの年率=p2(cs), QQQの年率=p2(cq), SPYとの差=p2(c - cs), QQQとの差=p2(c - cq), 抜けた月あり=gap)

    # ② 共通の窓
    win = {}
    for lab, a in WINDOWS.items():
        ms = months(a, LAST)
        rows = {}
        for t in list(A) + list(B) + CMP:
            if all(m in ser[t] for m in ms):
                rows[t] = window_row(ser[t], ser, ms)
        win[lab] = dict(窓=f'{ms[0]}〜{ms[-1]}', 月数=len(ms), 本=rows)

    # ③ 暦年・下げの局面
    years = {}
    for y in range(2014, 2027):
        ms = months(y * 100 + 1, min(y * 100 + 12, LAST))
        years[str(y) + ('（1〜9月）' if y == 2026 else '')] = {t: p2(total(ser[t], ms), 1) for t in tick if all(m in ser[t] for m in ms)}
    episodes = {}
    for lab, (a, b) in {'2020年2〜3月（コロナ）': (202002, 202003), '2022年（テックの下げ）': (202201, 202212),
                        '2025年2〜4月（関税）': (202502, 202504)}.items():
        ms = months(a, b)
        episodes[lab] = {t: p2(total(ser[t], ms), 1) for t in tick if all(m in ser[t] for m in ms)}

    # ④ 転がる36か月（W1 の中・W1 の本）
    w1 = months(WINDOWS['W1 2013-11〜（2013年までにできた本）'], LAST)
    roll = {}
    for t in [t for t in list(A) + list(B) + ['QQQ'] if all(m in ser[t] for m in w1)]:
        diffs = []
        for i in range(len(w1) - 35):
            ms = w1[i:i + 36]
            diffs.append(cagr(ser[t], ms) - cagr(ser['SPY'], ms))
        roll[t] = dict(窓=len(diffs), SPYを上回った割合=round(sum(d > 0 for d in diffs) / len(diffs), 2),
                       差の中央値=p2(S.median(diffs)), 差の最小=p2(min(diffs)), 差の最大=p2(max(diffs)))

    # ⑤ 日本の器（円）
    fx, fx_url = U.fred_monthly_last('DEXJPUS')
    jp_ser, jp_info = {}, {}
    for name, kind, ident, twin, fee, est, what in D:
        if kind == '投信':
            s, bad, d0 = nav_monthly(*ident)
            src = f'投信ライブラリー 基準価額 CSV（{ident[0]}・最初の日 {d0}・読めない行 {bad}）'
        else:
            s = {m: v for m, v in M.yahoo(ident).items() if m <= LAST}
            src = f'Yahoo {ident}（円・調整後終値）'
        s = {m: v for m, v in s.items() if m >= first_full_month(est) and m <= LAST}
        jp_ser[name] = s
        ms = [m for m in months(min(s), LAST)] if s else []
        complete = bool(ms) and all(m in s for m in ms)
        odd = {m: p2(v, 1) for m, v in s.items() if abs(v) > 0.30}
        row = dict(種類=kind, 何の型か=what, 信託報酬_税込=fee, 設定日=est, 系列=src, 窓=f'{ms[0]}〜{ms[-1]}' if ms else None, 月数=len(ms),
                   抜けた月なし=complete, 月に30パーセント超の動き=odd or None)
        if complete:
            comp = {'本体': s, 'SPY（円）': to_jpy(ser['SPY'], fx), 'QQQ（円）': to_jpy(ser['QQQ'], fx)}
            if twin:
                tw = ser.get(twin) or {m: v for m, v in M.yahoo(twin).items() if m <= LAST}
                comp[f'{twin}（円）'] = to_jpy(tw, fx)
            res = {}
            for k, x in comp.items():
                if all(m in x for m in ms):
                    res[k] = dict(累計=p2(total(x, ms), 1), 年率=p2(cagr(x, ms)) if len(ms) >= 12 else None)
                else:
                    res[k] = '同じ月の値がそろわない'
            row['同じ月の比べ'] = res
        jp_info[name] = row

    doc = dict(generated=datetime.date.today().isoformat(), tool='night/factor_etf_rakuten.py', kind='参考・判定なし（並べるだけ）',
               question='ユーザー「楽天にqualやMTUMのような優良ETFないの？」', data_last=LAST, 楽天で買えるか=rk,
               設定来=since, 共通の窓=win, 暦年=years, 下げの局面=episodes, 転がる36か月_W1=roll, 日本の器=jp_info,
               notes=['米国 ETF はドル建て・配当込み・費用は器のまま・税は引いていない（NISA で戻らない配当の外国税も引いていない）',
                      '円は月末の FRED DEXJPUS の比（' + fx_url + '）。日本の器の月末は米国の前日の終値まで＝米国 ETF の円換算と月ごとに少しずれる',
                      'SPY・QQQ との差は年率の差（pt）', '2026-10 の途中の月は含めない（2026-09 まで）',
                      'SMT 米国株式モメンタムは指数に連動しない（運用会社の決まりで選ぶ）。MTUM は比べるための近い型で同じものではない'])
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)
    print(json.dumps(rk, ensure_ascii=False)[:600])
    for t, r in since.items():
        print(f"{t:<5} {r['窓']} 年率 {r['年率']} ぶれ {r['ぶれ']} 最大下落 {r['最大下落']} SPY差 {r['SPYとの差']} QQQ差 {r['QQQとの差']} 楽天 {r['楽天']}")
    for lab, w in win.items():
        print('■', lab, w['窓'])
        for t, r in w['本'].items():
            print(f"   {t:<5} {r}")
    for y, d in years.items():
        print(y, d)
    print(json.dumps(episodes, ensure_ascii=False))
    print(json.dumps(roll, ensure_ascii=False))
    print(json.dumps(jp_info, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
