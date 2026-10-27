#!/usr/bin/env python3
"""直近と100年の両方で釣り合いのよい形を探す（both_balance・参考・判定なし・2026-10-26）

ユーザーの問い「直近と100年の両方でバランスがいい形は？」。物差しは既存の2つをそのまま使う（新しい式を作らない）:
  直近＝unx_assets.measure の USD・崩れあり（2000-09〜）の枠: π加重の平均の年率・P15π・最大下落
  100年＝unx_assets.century_monthly: 30年の中央値・30年の最悪・20年の下位10%点
★回す前に固定したこと（このファイルを結果の前にコミット）
  候補: ETF だけの形・部品 QQQM・SMH・ITA・XLV・FBT・VOO（両方の物差しに写しがある本。SHLD は100年の写しが ITA と同じなので ITA にまとめる・
    GDX・XLU は100年で市場を大きく下回るので外す）。第1段 10%刻み（3,003通り）→第2段 第1段の上位3つの周り（5%刻み・各本±10まで）。
  釣り合いの点: 6つそれぞれの百分位の順位（第1段の母集団で）→ 直近の3つの平均と100年の3つの平均の「小さいほう」を最大に（弱い側を上げる）。
  併せて出す: 今の形（全体の形・個別株＝席の業種の写し）と6つ全部で同じか上の形の一覧（上位10・釣り合いの点の順）。
  ⚠ 限界: 直近は2000年以降のテックの時代、100年は後から勝ちが分かった業種＝どちらも過去の写し。個別株・費用・税・為替の一部は入らない。
"""
import itertools, json, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'out', 'both_balance.json')
ASSETS = ['QQQM', 'SMH', 'ITA', 'XLV', 'FBT', 'VOO']
KEYS = ('mean', 'p15', 'dd', 'c30m', 'c30w', 'c20p')


def grid(step):
    n, k = 100 // step, len(ASSETS)
    for c in itertools.combinations(range(n + k - 1), k - 1):
        prev, w = -1, []
        for x in c:
            w.append(x - prev - 1); prev = x
        w.append(n + k - 2 - prev)
        yield {a: v * step for a, v in zip(ASSETS, w) if v > 0}


def name(f):
    return '/'.join(f'{k}{int(v) if float(v).is_integer() else v}' for k, v in f.items() if v > 0)


def evaluate(forms, U, UC, rows, chains, mega):
    out = {}
    names = list(forms)
    for s in range(0, len(names), 200):
        part = {n: forms[n] for n in names[s:s + 200]}
        tab = U.measure(part, rows, chains, mega=mega, windows={UC.W_CRASH: __import__('bestpf_check').WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
        for n, f in part.items():
            r = tab[n]['_raw'] if '_raw' in tab[n] else {}
            c = U.century_monthly(f)
            c30, c20 = c['30年の積立（起点1965〜1995）'], c['20年の積立（起点1965〜2005）']
            out[n] = dict(form=f, mean=tab[n]['π加重の平均の年率'], p15=tab[n]['P15π'], dd=tab[n]['最大下落'],
                          past=tab[n]['過去の転がる20年で15%以上'], c30m=c30['_med'], c30w=c30['最悪'], c20p=c20['_p10'],
                          c30beat=c30['市場に勝った割合'], c20beat=c20['市場に勝った割合'])
        U.log('評価', len(out), '/', len(names))
    return out


def main():
    import unx_assets as U
    import upside_check as UC
    t0 = time.time()
    res = U.build(); rows, chains = res['rows'], res['chains']
    mega = U.mega_map(rows, sorted(set(ASSETS) | {'SHLD'}))
    cc, _, _ = U.castle_copy()
    cur = U.whole({'QQQM': 40, 'SMH': 25, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5}, cc)
    refs = {'今（全体の形）': cur,
            '案1 NDX40/SMH30/ITA15/SHLD5/XLV5/FBT5': {'QQQM': 40, 'SMH': 30, 'ITA': 15, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
            '100年の釣り合い SMH15/ITA35/FBT50': {'SMH': 15, 'ITA': 35, 'FBT': 50},
            'NASDAQ100 だけ': {'QQQM': 100}, 'S&P500 だけ': {'VOO': 100}}
    st1 = {name(f): f for f in grid(10)}
    ev = evaluate({**st1, **refs}, U, UC, rows, chains, mega)
    base = [ev[n] for n in st1]
    vals = {k: np.array([b[k] for b in base]) for k in KEYS}

    def pct(k, x):                    # 第1段の母集団での百分位（高いほどよい・最大下落は負の数なので大きいほうがよい）
        return float((vals[k] < x).mean() + 0.5 * (vals[k] == x).mean())

    def score(e):
        a = np.mean([pct(k, e[k]) for k in KEYS[:3]]); b = np.mean([pct(k, e[k]) for k in KEYS[3:]])
        return float(min(a, b)), float(a), float(b)

    for e in ev.values():
        e['score'], e['recent_rank'], e['century_rank'] = score(e)
    top3 = sorted(st1, key=lambda n: -ev[n]['score'])[:3]
    st2 = {}
    for n in top3:
        f0 = ev[n]['form']
        for f in grid(5):
            if all(abs(f.get(a, 0) - f0.get(a, 0)) <= 10 for a in ASSETS):
                st2[name(f)] = f
    st2 = {k: v for k, v in st2.items() if k not in ev}
    ev.update(evaluate(st2, U, UC, rows, chains, mega))
    for e in ev.values():
        e['score'], e['recent_rank'], e['century_rank'] = score(e)
    cand = [n for n in ev if n not in refs]
    best = sorted(cand, key=lambda n: -ev[n]['score'])[:15]
    c0 = ev['今（全体の形）']
    dom = [n for n in cand if all(ev[n][k] >= c0[k] for k in KEYS)]
    dom = sorted(dom, key=lambda n: -ev[n]['score'])[:10]
    rnd = lambda e: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in e.items()}
    doc = dict(generated=time.strftime('%Y-%m-%d'), tool='night/both_balance.py', kind='参考・判定なし', 通り=len(ev) - len(refs),
               釣り合いの上位=[{'名前': n, **rnd(ev[n])} for n in best], 今を6つ全部で上回る形=[{'名前': n, **rnd(ev[n])} for n in dom],
               今を6つ全部で上回る形の数=len([n for n in cand if all(ev[n][k] >= c0[k] for k in KEYS)]),
               参考={n: rnd(ev[n]) for n in refs}, 秒=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    U.log('完了', doc['秒'], '秒')


if __name__ == '__main__':
    main()
