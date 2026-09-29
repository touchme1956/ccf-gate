#!/usr/bin/env python3
"""night/gaps_rebal.py — 歴史検証の穴④: 毎月リバランスの仮定と、実際の買い方（新しいお金を不足へだけ・売らない）（読むだけ）

事前登録: out/gaps7_prereg.json の Q4_rebalance（9c28f6c・測る前に固定）
  (a) 毎月もとの比率 QQQ75/SMH25 に戻す（売りも買いもする）
  (b) 毎月の入金を『目標−保有』の不足の比で配る。不足の合計が入金より小さければ残りは目標の比。売らない
出力: out/gaps_rebal.json
"""
import json, os, statistics as S, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
from gaps_common import add_months
from gaps_yen import monthly_returns

OUT = os.path.join(BASE, 'out', 'gaps_rebal.json')
W = {'QQQ': 0.75, 'SMH': 0.25}


def run(rets, start, n, mode):
    h = {k: 0.0 for k in W}
    dev = []
    for i in range(n):
        m = add_months(start, i)
        V = sum(h.values())
        if mode == 'rebal':
            tot = V + 1
            h = {k: tot * W[k] for k in W}
        else:
            gaps = {k: max(0.0, W[k] * (V + 1) - h[k]) for k in W}
            G = sum(gaps.values())
            if G >= 1:
                for k in W:
                    h[k] += gaps[k] / G
            else:
                for k in W:
                    h[k] += gaps[k] + (1 - G) * W[k]
        for k in W:
            h[k] *= 1 + rets[k][m]
        tot = sum(h.values())
        dev.append(abs(h['SMH'] / tot - W['SMH']))
    return sum(h.values()) / n, max(dev), S.mean(dev)


def main():
    rets = {k: monthly_returns(k) for k in W}
    ms = sorted(set(rets['QQQ']) & set(rets['SMH']))
    last = max(m for m in ms if m < int(time.strftime('%Y%m')))
    ms = [m for m in ms if m <= last]
    res = {}
    for n in (120, 180, 240):
        rows = []
        for s in ms:
            if add_months(s, n - 1) > last:
                break
            a = run(rets, s, n, 'rebal')
            b = run(rets, s, n, 'gap')
            rows.append((s, a, b))
        va = sorted(r[1][0] for r in rows)
        vb = sorted(r[2][0] for r in rows)
        res[f'{n // 12}年'] = {'窓': len(rows),
                              '毎月リバランス 中央/最悪': [round(va[len(va) // 2], 3), round(va[0], 3)],
                              '不足へだけ（売らない） 中央/最悪': [round(vb[len(vb) // 2], 3), round(vb[0], 3)],
                              '差（不足÷リバランス−1）中央/最悪': [round(vb[len(vb) // 2] / va[len(va) // 2] - 1, 4), round(vb[0] / va[0] - 1, 4)],
                              '窓ごとの差の最大・最小': [round(max(r[2][0] / r[1][0] - 1 for r in rows), 4), round(min(r[2][0] / r[1][0] - 1 for r in rows), 4)],
                              'SMHの比率のずれ（不足へだけ）: 窓ごとの最大の中央値・平均の中央値': [
                                  round(S.median(r[2][1] for r in rows) * 100, 1), round(S.median(r[2][2] for r in rows) * 100, 1)]}
    d20 = res['20年']['差（不足÷リバランス−1）中央/最悪']
    if abs(d20[0]) <= 0.05 and abs(d20[1]) <= 0.05:
        vd = '毎月リバランスの仮定は近似として妥当'
    elif abs(d20[0]) > 0.10 or abs(d20[1]) > 0.10:
        vd = '妥当でない'
    else:
        vd = '弱い'
    doc = {'generated': time.strftime('%Y-%m-%d'), 'tool': 'night/gaps_rebal.py', 'prereg': 'out/gaps7_prereg.json Q4_rebalance（9c28f6c）',
           '期間': f'{ms[0]}〜{last}', '判定': vd, '結果': res, '注': 'ドル建て・配当込み（Yahoo adjclose）。個別株20%はこの計算に入れていない'}
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('判定', vd)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
