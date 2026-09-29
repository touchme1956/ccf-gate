#!/usr/bin/env python3
"""night/gaps_yen.py — 歴史検証の穴①: 円で見た積立と、為替ヘッジをしない判断（読むだけ・判定に不使用）

事前登録: out/gaps7_prereg.json の Q1_yen（9c28f6c・測る前に固定）
  A … 今の配分（ETF側 QQQ75/SMH25）は円でも S&P500 より上か（20年の中央と最悪）
  B … 2000-06〜2001-12 に始めた積立は円でも報われたか（記述）
  C … 米国株（French 市場）の円の20年積立で、ヘッジなしとヘッジありのどちらが勝ったか（1971-01〜2005-12開始）
出力: out/gaps_yen.json
"""
import json, os, statistics as S, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
from gaps_common import fred, french_mkt, french_country, add_months, dca
import etf_theme as T

OUT = os.path.join(BASE, 'out', 'gaps_yen.json')


def monthly_returns(sym):
    px = T.fetch(sym)
    ks = sorted(px)
    out = {}
    for a, b in zip(ks, ks[1:]):
        out[int(b[:4]) * 100 + int(b[5:7])] = px[b] / px[a] - 1
    return out


def to_jpy(rets, fx):
    out = {}
    for m, r in rets.items():
        p = add_months(m, -1)
        if m in fx and p in fx:
            out[m] = (1 + r) * fx[m] / fx[p] - 1
    return out


def mix(parts, weights):
    ms = set.intersection(*[set(p) for p in parts])
    return {m: sum(w * p[m] for p, w in zip(parts, weights)) for m in ms}


def windows(rets, n, lo=None, hi=None):
    ms = sorted(rets)
    last = ms[-1]
    res = []
    for s in ms:
        if add_months(s, n - 1) > last:
            break
        if lo and s < lo or hi and s > hi:
            continue
        m, r = dca(rets, s, n)
        if m is not None:
            res.append((s, m, r))
    return res


def summ(ws):
    if not ws:
        return None
    v = sorted(x[1] for x in ws)
    return {'窓': len(ws), '中央': round(v[len(v) // 2], 3), '最悪': round(v[0], 3), '最良': round(v[-1], 3)}


def main():
    fx = fred('DEXJPUS')
    usd = {s: monthly_returns(s) for s in ('QQQ', 'SMH', 'SPY')}
    first = max(min(r) for r in usd.values())
    usd = {s: {m: v for m, v in r.items() if m >= first} for s, r in usd.items()}
    last_full = max(m for m in set.intersection(*[set(r) for r in usd.values()]) if m < int(time.strftime('%Y%m')))
    usd = {s: {m: v for m, v in r.items() if m <= last_full} for s, r in usd.items()}
    cands = {'今の配分（QQQ75/SMH25）': ([usd['QQQ'], usd['SMH']], [.75, .25]), 'QQQのみ': ([usd['QQQ']], [1.0]),
             'S&P500のみ（SPY）': ([usd['SPY']], [1.0])}
    A, B = {}, {}
    for nm, (parts, w) in cands.items():
        r_usd = mix(parts, w)
        r_jpy = to_jpy(r_usd, fx)
        A[nm] = {cur: {f'{n // 12}年': summ(windows(r, n)) for n in (120, 180, 240)} for cur, r in (('ドル', r_usd), ('円', r_jpy))}
        B[nm] = {cur: {f'{n // 12}年': summ(windows(r, n, 200006, 200112)) for n in (120, 180, 240)} for cur, r in (('ドル', r_usd), ('円', r_jpy))}
    a20 = {nm: A[nm]['円']['20年'] for nm in A}
    mixk, spk = '今の配分（QQQ75/SMH25）', 'S&P500のみ（SPY）'
    verdictA = ('円でも順位は変わらない' if a20[mixk]['中央'] >= a20[spk]['中央'] and a20[mixk]['最悪'] >= a20[spk]['最悪'] else '変わる')

    # --- C: 米国株（French 市場）を円で。ヘッジあり・なし ---
    mkt, rf = french_mkt()
    us_rate = fred('TB3MS')
    jp_call = fred('IRSTCI01JPM156N')
    jp_disc = fred('INTDSRJPM193N')

    def jp_rate(m):
        if m >= 198507 and m in jp_call:
            return jp_call[m], 'call'
        if m in jp_disc:
            return jp_disc[m], 'discount'
        return None, None
    un, he, src = {}, {}, {}
    for m, r in mkt.items():
        p = add_months(m, -1)
        if m < 197101 or m not in fx or p not in fx:
            continue
        ij, s = jp_rate(p)                    # 前月末に1か月の予約を組む
        iu = us_rate.get(p)
        if ij is None or iu is None:
            continue
        un[m] = (1 + r) * fx[m] / fx[p] - 1
        he[m] = (1 + r) * (1 + (ij - iu) / 1200) - 1
        src[m] = s

    def race(lo, hi, n=240):
        wu = {s: m for s, m, _ in windows(un, n, lo, hi)}
        wh = {s: m for s, m, _ in windows(he, n, lo, hi)}
        ks = sorted(set(wu) & set(wh))
        if not ks:
            return None
        wins = sum(wu[k] > wh[k] for k in ks)
        return {'窓': len(ks), 'ヘッジなしが勝った窓': wins, '割合': round(wins / len(ks), 3),
                'ヘッジなし 中央/最悪': [round(S.median(wu[k] for k in ks), 3), round(min(wu[k] for k in ks), 3)],
                'ヘッジあり 中央/最悪': [round(S.median(wh[k] for k in ks), 3), round(min(wh[k] for k in ks), 3)],
                '起点ごと(5年刻み)': {str(k // 100): {'なし': round(wu[k], 2), 'あり': round(wh[k], 2)} for k in ks if k % 100 == 1 and (k // 100) % 5 == 0}}
    Cmain = race(197101, 200512)
    frac = Cmain['割合']
    medu, medh = Cmain['ヘッジなし 中央/最悪'][0], Cmain['ヘッジあり 中央/最悪'][0]
    if frac >= 0.6 and medu > medh:
        verdictC = '『ヘッジしない』を支持'
    elif (1 - frac) >= 0.6:
        verdictC = '否定（ヘッジありが勝つ）'
    else:
        verdictC = '弱い'
    Csub = {'1985-07以降に始めた窓（金利が実データ）': race(198507, 200512),
            '15年窓・全期間': race(197101, 201012, 180), '10年窓・全期間': race(197101, 201512, 120)}
    # QQQ の時代: 今の配分をヘッジした場合
    mixu = mix(cands[mixk][0], cands[mixk][1])
    mh, mu = {}, {}
    for m, r in mixu.items():
        p = add_months(m, -1)
        ij, _ = jp_rate(p)
        iu = us_rate.get(p)
        if ij is None or iu is None or m not in fx or p not in fx:
            continue
        mu[m] = (1 + r) * fx[m] / fx[p] - 1
        mh[m] = (1 + r) * (1 + (ij - iu) / 1200) - 1
    un_bak, he_bak = un, he
    un, he = mu, mh
    Cqqq = {f'{n // 12}年': race(None, None, n) for n in (120, 180, 240)}
    un, he = un_bak, he_bak
    # 日本株（円・配当込み）の20年積立と、円で見た米国株のぶれ
    jp = french_country('Japan', 'Local')
    jpw = summ(windows(jp, 240, 197501, 200512))
    usw = summ([w for w in windows(un, 240, 197501, 200512)])

    def vol(r, ks):
        v = [r[k] for k in ks]
        return round(S.pstdev(v) * (12 ** .5) * 100, 1)
    ks = sorted(k for k in un if k >= 197101)
    fxr = {m: fx[m] / fx[add_months(m, -1)] - 1 for m in ks if add_months(m, -1) in fx}
    xs = [(mkt[m], fxr[m]) for m in ks if m in fxr]
    mx, mf = S.mean(a for a, _ in xs), S.mean(b for _, b in xs)
    corr = sum((a - mx) * (b - mf) for a, b in xs) / ((sum((a - mx) ** 2 for a, _ in xs) * sum((b - mf) ** 2 for _, b in xs)) ** .5)
    doc = {'generated': time.strftime('%Y-%m-%d'), 'tool': 'night/gaps_yen.py', 'prereg': 'out/gaps7_prereg.json Q1_yen（9c28f6c）',
           '期間_ETF': f'{min(mixu)}〜{last_full}', '判定A': verdictA, 'A_円とドルの積立の倍率': A,
           'B_2000-06〜2001-12に始めた積立': B, '判定C': verdictC, 'C_米国株の20年積立_円_1971〜2005開始': Cmain, 'C_副': Csub,
           'C_今の配分をヘッジした場合（2000年〜）': Cqqq,
           '参考_日本株（円・配当込み）の20年積立・1975〜2005開始': jpw, '参考_米国株（円・ヘッジなし）同じ窓': usw,
           '参考_円で見たぶれ（年率%）': {'米国株・ドル': vol(mkt, ks), '米国株・円（ヘッジなし）': vol(un, ks), '米国株・円（ヘッジあり）': vol(he, ks)},
           '参考_米国株のリターンとドル高の相関（月次）': round(corr, 3),
           '注': 'ヘッジは毎月の為替予約の巻き直し・手数料0。日本の金利は1985-07から短期金利（コール）、それ以前は公定歩合で代用。ETFは配当込みの adjclose'}
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('判定A', verdictA, '判定C', verdictC)
    print('A 円20年', a20)
    print('A ドル20年', {nm: A[nm]['ドル']['20年'] for nm in A})
    print('B', {nm: {c: B[nm][c]['20年'] for c in B[nm]} for nm in B})
    print('C', {k: v for k, v in Cmain.items() if k != '起点ごと(5年刻み)'})
    print('C 起点ごと', Cmain['起点ごと(5年刻み)'])
    for k, v in Csub.items():
        print('C副', k, {kk: vv for kk, vv in (v or {}).items() if kk != '起点ごと(5年刻み)'})
    for k, v in Cqqq.items():
        print('C今の配分', k, {kk: vv for kk, vv in (v or {}).items() if kk != '起点ごと(5年刻み)'})
    print('日本株', jpw, '米国株円', usw, 'ぶれ', doc['参考_円で見たぶれ（年率%）'], '相関', doc['参考_米国株のリターンとドル高の相関（月次）'])


if __name__ == '__main__':
    main()
