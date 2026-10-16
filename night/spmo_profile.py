#!/usr/bin/env python3
"""night/spmo_profile.py — SPMO（Invesco S&P 500 Momentum ETF）とは（2026-10-16・ユーザー「SPMOとは？」・参考・判定なし）

読むだけ。門・採点・配分・注文書には触れない。判定はしない（並べるだけ）。測り方は結果を見る前にこのファイルで固定する。
  ① 器の事実: Alpha Vantage ETF_PROFILE（2026-10-16 の写し out/_nx_cache/spmo/SPMO_av_profile_20261016.json・gitignore）の
     経費率・純資産・回転率・配当利回り・設定日・業種・保有（GOOG と GOOGL は1社にまとめる）。上位10社の合計・本数
  ② 今の ETF 側（portfolio.json の ami_weights。IFREE-NDX は同じ指数の QQQM の中身で写す・目標0%の本は外す）との重なり:
     Σmin（SPMO の重さ, ETF 側の重さ）。ETF 側の中身は out/etf_profiles.json（本ごとに asof が違う）。主な巨大株の重さも並べる
  ③ 実績: out/factor_etf_rakuten.json（331541bd で固定した物差し）から SPMO の設定来・窓・暦年・下げの局面を写す
  ④ 長い歴史: French の 6_Portfolios_ME_Prior_12_2 の BIG HiPRIOR（大型株のうち過去12か月〔直近1か月を除く〕の上昇率の上位30%・
     時価総額加重・費用なし）を French の市場（Mkt-RF＋RF）と比べる。期間 1927-01〜（全期間）・1927〜1949・1950〜1979・1980〜2006・
     2007〜・2013-07〜。年率・差・市場を下回った暦年の差の大きい5回・最大下落・転がる10年・20年で市場を上回った割合
  ⑤ 9月の入れ替えの目安: 主な社の 2025-08〜2026-07 の12か月の上昇率（月次・配当込み）と、それを月次のぶれ（年率）で割った値
     （S&P の勢いの値の近似。正確な値は日次のぶれと公式の基準日で決まる）
使い方: python3 night/spmo_profile.py → out/spmo_profile.json
"""
import datetime, json, math, os, statistics as S, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import mw_common as M          # noqa: E402

OUT = os.path.join(BASE, 'out', 'spmo_profile.json')
AV = os.path.join(BASE, 'out', '_nx_cache', 'spmo', 'SPMO_av_profile_20261016.json')
MEGA = ['NVDA', 'MSFT', 'AAPL', 'GOOGL', 'AMZN', 'META', 'AVGO', 'TSLA', 'TSM', 'MU', 'AMD', 'INTC', 'JNJ', 'XOM', 'LRCX']
MOM_NAMES = ['NVDA', 'MSFT', 'AAPL', 'GOOGL', 'AMZN', 'META', 'AVGO', 'TSLA', 'MU', 'AMD', 'INTC', 'LRCX', 'AMAT', 'JNJ', 'XOM', 'CSCO', 'SPY']
MOM_WIN = (202508, 202607)
PERIODS = {'全期間 1927〜': (192701, None), '1927〜1949': (192701, 194912), '1950〜1979': (195001, 197912),
           '1980〜2006': (198001, 200612), '2007〜': (200701, None), '2013-07〜': (201307, None)}


def months(a, b):
    out, y, m = [], a // 100, a % 100
    while y * 100 + m <= b:
        out.append(y * 100 + m)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def cagr(s, ms):
    return math.exp(sum(math.log1p(s[m]) for m in ms) * 12 / len(ms)) - 1


def mdd(s, ms):
    lvl, peak, worst = 1.0, 1.0, 0.0
    for m in ms:
        lvl *= 1 + s[m]
        peak = max(peak, lvl)
        worst = min(worst, lvl / peak - 1)
    return worst


def p2(x, k=2):
    return None if x is None else round(100 * x, k)


def main():
    # ① 器の事実
    av = json.load(open(AV))
    hold = {}
    for h in av['holdings']:
        t, w = h['symbol'], float(h['weight'])
        if t in ('n/a', 'AGPXX') or w <= 0:
            continue
        t = 'GOOGL' if t == 'GOOG' else t
        hold[t] = hold.get(t, 0.0) + w
    top = sorted(hold.items(), key=lambda x: -x[1])
    facts = dict(写し='out/_nx_cache/spmo/SPMO_av_profile_20261016.json（Alpha Vantage ETF_PROFILE・last_updated ' + av['last_updated'] + '）',
                 経費率=float(av['net_expense_ratio']), 純資産_ドル=float(av['net_assets']), 回転率=float(av['portfolio_turnover']),
                 配当利回り=float(av['dividend_yield']), 設定日=av['inception_date'], 本数=len(hold),
                 上位10社=[(t, p2(w)) for t, w in top[:10]], 上位10社の合計=p2(sum(w for _, w in top[:10]), 1),
                 業種={s['sector']: p2(float(s['weight']), 1) for s in av['sectors']})

    # ② 今の ETF 側との重なり
    tgt = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    prof = json.load(open(os.path.join(BASE, 'out', 'etf_profiles.json')))['etfs']
    alias = {'IFREE-NDX': 'QQQM'}
    wts = {alias.get(k, k): float(v) for k, v in tgt['ami_weights'].items() if float(v) > 0}
    miss = [k for k in wts if k not in prof]
    assert not miss, f'etf_profiles.json に中身が無い本: {miss}'
    tot = sum(wts.values())
    cur, asof = {}, {}
    for k, w in wts.items():
        asof[k] = prof[k].get('asof')
        for row in prof[k]['h']:
            t, x = row[0], float(row[1])
            if not t or t == 'n/a':
                continue
            t = 'GOOGL' if t == 'GOOG' else t
            cur[t] = cur.get(t, 0.0) + w / tot * x
    keys = set(hold) | set(cur)
    ov_all = sum(min(hold.get(t, 0.0), cur.get(t, 0.0)) for t in keys)
    per_etf = {}
    for k in wts:
        hk = {}
        for row in prof[k]['h']:
            if row[0] and row[0] != 'n/a':
                t = 'GOOGL' if row[0] == 'GOOG' else row[0]
                hk[t] = hk.get(t, 0.0) + float(row[1])
        per_etf[k] = p2(sum(min(hold.get(t, 0.0), hk.get(t, 0.0)) for t in set(hold) | set(hk)), 1)
    overlap = dict(ETF側の目標=dict(wts), 中身の日付=asof, ETF側全体との重なり=p2(ov_all, 1), 本ごとの重なり=per_etf,
                   主な社の重さ={t: dict(SPMO=p2(hold.get(t, 0.0)), 今のETF側=p2(cur.get(t, 0.0))) for t in MEGA})

    # ③ 実績（factor_etf_rakuten の写し）
    fr = json.load(open(os.path.join(BASE, 'out', 'factor_etf_rakuten.json')))
    rec = dict(設定来=fr['設定来']['SPMO'], 窓={k: dict(SPMO=v['本'].get('SPMO'), SPY=v['本'].get('SPY'), QQQ=v['本'].get('QQQ'))
                                              for k, v in fr['共通の窓'].items() if 'SPMO' in v['本']},
               暦年={y: dict(SPMO=d.get('SPMO'), SPY=d.get('SPY'), QQQ=d.get('QQQ')) for y, d in fr['暦年'].items() if d.get('SPMO') is not None},
               下げの局面={k: dict(SPMO=d.get('SPMO'), SPY=d.get('SPY'), QQQ=d.get('QQQ')) for k, d in fr['下げの局面'].items()})
    yrs = rec['暦年']
    rec['SPYを上回った暦年'] = f"{sum(1 for d in yrs.values() if d['SPMO'] > d['SPY'])} / {len(yrs)}"
    rec['QQQを上回った暦年'] = f"{sum(1 for d in yrs.values() if d['SPMO'] > d['QQQ'])} / {len(yrs)}"

    # ④ 長い歴史（French）
    hp = M.french_series('6_Portfolios_ME_Prior_12_2', want='Average Value Weighted Returns')['BIG HiPRIOR']
    mk = M.ff_factors()['mkt']
    common = sorted(set(hp) & set(mk))
    last = common[-1]
    long = {}
    for lab, (a, b) in PERIODS.items():
        ms = [m for m in months(a, b or last) if m in hp and m in mk]
        c, cm = cagr(hp, ms), cagr(mk, ms)
        long[lab] = dict(窓=f'{ms[0]}〜{ms[-1]}', 勢いの上位30パーセント=p2(c), 市場=p2(cm), 差=p2(c - cm),
                         最大下落_勢い=p2(mdd(hp, ms), 1), 最大下落_市場=p2(mdd(mk, ms), 1))
    yd = {}
    for y in range(1927, last // 100 + 1):
        ms = [m for m in months(y * 100 + 1, y * 100 + 12) if m in hp and m in mk]
        if len(ms) == 12:
            yd[y] = (math.prod(1 + hp[m] for m in ms) - 1, math.prod(1 + mk[m] for m in ms) - 1)
    worst = sorted(yd.items(), key=lambda kv: kv[1][0] - kv[1][1])[:5]
    roll = {}
    for n in (120, 240):
        allm = [m for m in common]
        diffs = [cagr(hp, allm[i:i + n]) - cagr(mk, allm[i:i + n]) for i in range(len(allm) - n + 1)]
        roll[f'{n // 12}年'] = dict(窓=len(diffs), 市場を上回った割合=round(sum(d > 0 for d in diffs) / len(diffs), 2),
                                   差の中央値=p2(S.median(diffs)), 差の最小=p2(min(diffs)))
        late = [cagr(hp, allm[i:i + n]) - cagr(mk, allm[i:i + n]) for i in range(len(allm) - n + 1) if allm[i] >= 199701]
        roll[f'{n // 12}年'][f'1997年以降に始めた窓'] = dict(窓=len(late), 市場を上回った割合=round(sum(d > 0 for d in late) / len(late), 2) if late else None)
    hist = dict(出所='Ken French 6_Portfolios_ME_Prior_12_2（BIG HiPRIOR・時価総額加重）と F-F_Research_Data_Factors（Mkt-RF＋RF）', 最後の月=last,
                期間=long, 市場に大きく負けた暦年=[dict(年=y, 勢い=p2(a, 1), 市場=p2(b, 1), 差=p2(a - b, 1)) for y, (a, b) in worst],
                市場を上回った暦年=f"{sum(1 for a, b in yd.values() if a > b)} / {len(yd)}", 転がる窓=roll)

    # ⑤ 9月の入れ替えの目安
    ms = months(*MOM_WIN)
    mom = {}
    for t in MOM_NAMES:
        s = M.yahoo(t)
        if not all(m in s for m in ms):
            mom[t] = '値がそろわない'
            continue
        r12 = math.prod(1 + s[m] for m in ms) - 1
        v = S.pstdev([s[m] for m in ms]) * math.sqrt(12)
        mom[t] = dict(上昇率_12か月=p2(r12, 1), ぶれ_年率=p2(v, 1), 上昇率をぶれで割った値=round(r12 / v, 2) if v else None,
                      SPMOの重さ=p2(hold.get(t, 0.0)))
    momd = dict(窓=f'{ms[0]}〜{ms[-1]}（月次・配当込み）', 注意='S&P の勢いの値の近似（公式は基準日・日次のぶれで計算）', 社=mom)

    doc = dict(generated=datetime.date.today().isoformat(), tool='night/spmo_profile.py', kind='参考・判定なし（並べるだけ）',
               question='ユーザー「SPMOとは？」', 器=facts, 今のETF側との重なり=overlap, 実績=rec, 長い歴史=hist, 九月の入れ替えの目安=momd,
               notes=['SPMO は楽天の海外 ETF 一覧（2026-10-16）に無い（out/factor_etf_rakuten.json の 楽天で買えるか）',
                      '重なりは中身の日付が本ごとに違う（SPMO 2026-10-16・他は etf_profiles.json の asof）',
                      'French の勢いの上位30%は SPMO（S&P500 の約100社・ぶれで割った勢い・時価総額×勢いの重み・年2回）と同じ作りではない'])
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)
    print(json.dumps(facts, ensure_ascii=False))
    print(json.dumps(overlap, ensure_ascii=False))
    print(json.dumps({k: v for k, v in rec.items() if k != '暦年'}, ensure_ascii=False)[:2500])
    print(json.dumps(hist, ensure_ascii=False))
    print(json.dumps(momd, ensure_ascii=False))


if __name__ == '__main__':
    main()
