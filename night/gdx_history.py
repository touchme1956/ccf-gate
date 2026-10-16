#!/usr/bin/env python3
"""night/gdx_history.py — GDX（金鉱株 ETF）の過去のリターン（2026-10-16・ユーザー「GDXのかこのリターンは？」・参考・判定なし）

読むだけ。門・採点・配分・注文書には触れない。判定はしない（並べるだけ）。測り方は結果を見る前にこのファイルで固定する。
  系列（ドル建て・配当込みの月次・Yahoo の調整後終値＝mw_common.yahoo）:
    GDX（2006-05-16 設定＝2006-06 から）・比べる相手 SPY（S&P500）・QQQ（NASDAQ100）・GLD（金そのもの・2004-12〜）
    長い代わり: FSAGX（Fidelity Select Gold・金鉱株の投信）を GDX の前につなぐ（unx_assets と同じつなぎ・2006-05 まで）
    もっと長い代わり: Ken French の49業種の Gold（時価総額加重・future30.load と同じ表）と同じ表の米国株全体
  円: 月末の FRED DEXJPUS の比を掛ける（unx_assets.jpy_chains と同じ）
  出すもの: 期間の年率（全期間・20/15/10/5/3/1年・2026-09 まで）・暦年・最大下落と回復までの月数・下げの大きい3回・
    長い代わりの年率（1963〜／1986〜）・毎月の積立（20年）の内部収益率の転がる窓（代わりをつないだ系列・SPY と比べる）
使い方: python3 night/gdx_history.py → out/gdx_history.json
"""
import datetime, json, math, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import mw_common as M          # noqa: E402
import unx_assets as U         # noqa: E402
import bestpf_realized as BR   # noqa: E402

OUT = os.path.join(BASE, 'out', 'gdx_history.json')
LAST = 202609
GDX_FIRST = 200606
SPLICE_LAST = 200605
PERIODS = {'全期間（GDX の本物・2006-06〜）': GDX_FIRST, '直近20年（2006-10〜）': 200610, '直近15年（2011-10〜）': 201110,
           '直近10年（2016-10〜）': 201610, '直近5年（2021-10〜）': 202110, '直近3年（2023-10〜）': 202310, '直近1年（2025-10〜）': 202510}


def months(a, b):
    return BR.months(a, b)


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


def drawdowns(s, ms, top=3):
    """月末の水準で最大下落の山（ピーク→谷→回復）を大きい順に top 本"""
    lvl, peak, peak_m = 1.0, 1.0, ms[0]
    eps, cur = [], None
    for m in ms:
        lvl *= 1 + s[m]
        if lvl >= peak:
            if cur:
                cur['回復'] = m
                eps.append(cur)
                cur = None
            peak, peak_m = lvl, m
        else:
            dd = lvl / peak - 1
            if cur is None:
                cur = {'山': peak_m, '谷': m, '下落': dd}
            elif dd < cur['下落']:
                cur['谷'], cur['下落'] = m, dd
    if cur:
        cur['回復'] = None
        eps.append(cur)
    eps.sort(key=lambda e: e['下落'])
    out = []
    for e in eps[:top]:
        n_down = (e['谷'] // 100 * 12 + e['谷'] % 100) - (e['山'] // 100 * 12 + e['山'] % 100)
        n_rec = None if e['回復'] is None else (e['回復'] // 100 * 12 + e['回復'] % 100) - (e['山'] // 100 * 12 + e['山'] % 100)
        out.append({'山（月末）': e['山'], '谷': e['谷'], '下落(%)': round(100 * e['下落'], 1), '谷まで(か月)': n_down,
                    '高値を取り戻した月': e['回復'] or '未回復（2026-09 まで）', '山から回復まで(か月)': n_rec})
    return out


def to_jpy(s, fx):
    out = {}
    for m, v in s.items():
        p = U.months_add(m, -1)
        if m in fx and p in fx:
            out[m] = (1 + v) * fx[m] / fx[p] - 1
    return out


def r2(x, k=2):
    return None if x is None else round(100 * x, k)


def main():
    raw = {t: M.yahoo(t) for t in ('GDX', 'SPY', 'QQQ', 'GLD', 'FSAGX')}
    gdx = {m: v for m, v in raw['GDX'].items() if GDX_FIRST <= m <= LAST}
    spy, qqq, gld = ({m: v for m, v in raw[t].items() if m <= LAST} for t in ('SPY', 'QQQ', 'GLD'))
    fsagx = {m: v for m, v in raw['FSAGX'].items() if m <= LAST}
    chain = {m: v for m, v in fsagx.items() if m <= SPLICE_LAST}
    chain.update(gdx)
    ov = [m for m in months(GDX_FIRST, LAST) if m in fsagx and m in gdx]
    splice = {'代わり': 'FSAGX（Fidelity Select Gold）', 'つなぎ目': f'{SPLICE_LAST} まで FSAGX・{GDX_FIRST} から GDX',
              '重なる月': len(ov), '相関': round(M.corr([gdx[m] for m in ov], [fsagx[m] for m in ov]), 4),
              '重なる窓の年率 GDX / FSAGX': [r2(cagr(gdx, ov)), r2(cagr(fsagx, ov))], 'FSAGX の最初の月': min(fsagx)}
    fx, fx_url = U.fred_monthly_last('DEXJPUS')
    ser = {'GDX（金鉱株）': gdx, 'S&P500（SPY）': spy, 'NASDAQ100（QQQ）': qqq, '金（GLD）': gld}
    ser_jpy = {k: to_jpy(v, fx) for k, v in ser.items()}

    per = {}
    for lab, a in PERIODS.items():
        ms = months(a, LAST)
        row = {}
        for k in ser:
            row[k] = dict(年率_ドル=r2(cagr(ser[k], ms)), 年率_円=r2(cagr(ser_jpy[k], ms)), 累計_ドル=r2(total(ser[k], ms), 1))
        per[lab] = row

    years = {}
    for y in range(2007, 2027):
        ms = months(y * 100 + 1, min(y * 100 + 12, LAST))
        years[str(y) + ('（1〜9月）' if y == 2026 else '')] = {k: r2(total(ser[k], ms), 1) for k in ser}

    ms_all = months(GDX_FIRST, LAST)
    risk = {k: dict(ぶれ_年率=r2(vol(ser[k], ms_all), 1), 下げの大きい3回=drawdowns(ser[k], ms_all)) for k in ('GDX（金鉱株）', 'S&P500（SPY）', 'NASDAQ100（QQQ）')}
    gdx_up = sum(1 for y, d in years.items() if d['GDX（金鉱株）'] is not None and d['S&P500（SPY）'] is not None and d['GDX（金鉱株）'] > d['S&P500（SPY）'])
    corr_q = round(M.corr([gdx[m] for m in ms_all], [qqq[m] for m in ms_all]), 3)
    corr_s = round(M.corr([gdx[m] for m in ms_all], [spy[m] for m in ms_all]), 3)

    # ── 長い代わり ──
    import future30 as F
    cols, ret, capm, me, be, share, mkt = F.load()
    gold_f = ret['Gold']
    f_first = min(m for m in gold_f if m in mkt)
    f_last = min(max(gold_f), max(mkt))
    fm = months(f_first, f_last)
    long_f = dict(期間=f'{f_first}〜{f_last}', 金鉱業_年率=r2(cagr(gold_f, fm)), 米国株全体_年率=r2(cagr(mkt, fm)),
                  金鉱業_ぶれ=r2(vol(gold_f, fm), 1), 金鉱業_下げの大きい3回=drawdowns(gold_f, fm))
    c_first = min(chain)
    cm = months(c_first, LAST)
    spy_first = max(c_first, min(spy))
    cm2 = months(spy_first, LAST)
    long_c = dict(期間=f'{c_first}〜{LAST}', FSAGXとGDXをつないだ系列_年率=r2(cagr(chain, cm)), 下げの大きい3回=drawdowns(chain, cm),
                  SPYと同じ窓=dict(期間=f'{spy_first}〜{LAST}', 金鉱株=r2(cagr(chain, cm2)), SPY=r2(cagr(spy, cm2))))

    # ── 毎月の積立（20年）の転がる窓（つないだ系列 と SPY）──
    n = 240
    starts = [m for m in months(spy_first, LAST) if U.months_add(m, n - 1) <= LAST]
    win = []
    for a in starts:
        ms = months(a, U.months_add(a, n - 1))
        if all(m in chain and m in spy for m in ms):
            g = BR.irr_monthly([chain[m] for m in ms])[0]
            s = BR.irr_monthly([spy[m] for m in ms])[0]
            win.append((a, g, s))
    gs = sorted(w[1] for w in win)
    dca = dict(窓=len(win), 起点=f'{win[0][0]}〜{win[-1][0]}' if win else None,
               金鉱株_中央=r2(gs[len(gs) // 2]) if gs else None, 金鉱株_最小=r2(gs[0]) if gs else None, 金鉱株_最大=r2(gs[-1]) if gs else None,
               SPY_中央=r2(sorted(w[2] for w in win)[len(win) // 2]) if win else None,
               金鉱株がSPYを上回った割合=round(sum(w[1] > w[2] for w in win) / len(win), 2) if win else None,
               今日で終わる20年=dict(金鉱株=r2(win[-1][1]) if win else None, SPY=r2(win[-1][2]) if win else None))
    last20 = months(U.months_add(LAST, -(n - 1)), LAST)
    dca['今日で終わる20年_QQQ'] = r2(BR.irr_monthly([qqq[m] for m in last20])[0]) if all(m in qqq for m in last20) else None

    doc = dict(generated=datetime.date.today().isoformat(), tool='night/gdx_history.py', kind='参考・判定なし（並べるだけ）',
               question='ユーザー「GDXのかこのリターンは？」', data_last=LAST,
               期間の年率=per, 暦年=years, 値動きの大きさと下げ=risk,
               GDXがSPYを上回った暦年=f'{gdx_up} / {len(years)}', 月次の相関=dict(NASDAQ100=corr_q, SP500=corr_s),
               つなぎ=splice, 長い代わり_French49のGold=long_f, 長い代わり_FSAGXとGDX=long_c, 毎月の積立20年=dca,
               notes=['ドル建て・配当込み・費用は器のまま（GDX 0.51%）・税は引いていない', '円は月末の FRED DEXJPUS の比（' + fx_url + '）',
                      '2026-10 の途中の月は含めない（2026-09 まで）', 'French の Gold は ETF ではなく業種の時価総額加重（費用なし）',
                      'FSAGX は能動の投信（金鉱株中心・金そのものも一部持つ時期がある）'])
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)
    for lab, row in per.items():
        print(lab, {k: (v['年率_ドル'], v['年率_円']) for k, v in row.items()})
    for y, d in years.items():
        print(y, d)
    print(json.dumps(risk, ensure_ascii=False)[:1500])
    print('相関', corr_q, corr_s, '暦年で SPY を上回った', gdx_up, '/', len(years))
    print('つなぎ', splice)
    print('French Gold', json.dumps(long_f, ensure_ascii=False)[:800])
    print('FSAGX+GDX', json.dumps(long_c, ensure_ascii=False)[:800])
    print('積立20年', dca)


if __name__ == '__main__':
    main()
