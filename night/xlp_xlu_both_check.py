#!/usr/bin/env python3
"""night/xlp_xlu_both_check.py — XLP と XLU を両方入れるなら、どの形にするか（2026-11-25・参考・配分は変えない）

ユーザー「XLPとXLU両方ポートフォリオに加えるならあなたはどうする？」
読み方（固定）: 「両方加える」＝ ETF 側で XLP ≥5% かつ XLU ≥5%。「どうする」＝ 同じ日の最適解の探し（night/ndx40_opt_check.py・書庫:22273）
  と同じ範囲・同じ物差し・同じ直したデータで、両方を含む形だけに絞って選ぶ。今の main（40/25/15/10/10）が相手。
★選び方はこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする。
  見たもの: ndx40_opt_check の出力（答え＝今の main・XLP を含む最良は5位 40/25/ITA 5/FBT 10/VBR 15/XLP 5 年15%以上 26.85・
    XLU を含む最良は8位 40/25/ITA 10/FBT 5/VBR 15/XLU 5 26.67・2本を両方含む形の数字は見ていない）。
範囲: ndx40_opt_check の2,684形のうち XLP ≥5 ∧ XLU ≥5 の形（NASDAQ100 40〜50・SMH 15〜35・ITA/FBT 5〜20・VBR/XLV/XLP/XLU 0〜20）。
選び方:
  ① 守りの5つ（年5%未満・最大下落 ドル/円・業種の基礎率の平均・100年の代用の30年の最悪 V1）が今の main より悪くならない形のうち、
     年15%以上の確率が最も高い形（並べ方は ndx40_opt_check と同じ）＝私の答え。
  ② ①を通る形が無ければ: 守りの5つのうち悪くならない数が多い順 → 年15%以上の確率の順。
併せて出す（答えを決めるのに使わない）: 両方5%ずつ（合計10%）の形の最良（①の条件で）／
  今の main から10%を出して XLP 5・XLU 5 を足す形（出す元の組み合わせごと・比べるだけ）／両方を含む形の年15%以上の天井。
使い方: python3 night/xlp_xlu_both_check.py → out/xlp_xlu_both_check.json（約1分・ndx40_opt_check の回帰の検査もそのまま通る）
"""
import os, sys, json
import numpy as np
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import ndx40_opt_check as NO  # noqa: E402

OUT = os.path.join(BASE, 'out', 'xlp_xlu_both_check.json')
DEF = [2, 3, 5, 8]   # Y の列（③④⑥⑨）＋円の最大下落は別


def extra(c):
    G, Y, mJ, cond, meas, order, row, yM, mJM, EPS = (c[k] for k in ('G', 'Y', 'mJ', 'cond', 'meas', 'order', 'row', 'yM', 'mJM', 'EPS'))
    both = np.array([g['XLP'] >= 5 and g['XLU'] >= 5 for g in G])
    nok = sum((Y[:, k] >= yM[k] - EPS).astype(int) for k in DEF) + (mJ >= mJM - EPS).astype(int)
    pas = order(cond & both)
    if pas:
        ans, how = pas[0], '①守りの5つを悪くしない中で年15%以上が最大'
    else:
        idx = [int(i) for i in np.where(both & meas)[0]]
        idx.sort(key=lambda i: (-int(nok[i]), -float(Y[i, 1])))
        ans, how = idx[0], '②（①を通る形が無い）悪くならない守りの数 → 年15%以上'
    five = np.array([g['XLP'] == 5 and g['XLU'] == 5 for g in G])
    p5 = order(cond & both & five)
    # 今の main から10を出して XLP5・XLU5
    MAIN = NO.MAIN
    srcs = []
    keys = ['QQQM', 'SMH', 'ITA', 'FBT', 'VBR']
    for a in keys:
        for b in keys:
            if a > b:
                continue
            f = {k: MAIN.get(k, 0) for k in NO.FUNDS}
            f[a] -= 5; f[b] -= 5; f['XLP'] = 5; f['XLU'] = 5
            if f[a] < 0 or f[b] < 0:
                continue
            nm = NO.name(f)
            if nm in c['names']:
                i = c['names'].index(nm)
                srcs.append(dict(出す元=f'{a} −5・{b} −5' if a != b else f'{a} −10', 守りを悪くしない=bool(cond[i]),
                                 悪くならない守りの数=int(nok[i]), **row(i)))
    srcs.sort(key=lambda d: -d['物差し13']['V1']['②年15%以上の確率'])
    ceil = order(both)
    return dict(両方を含む形の数=int(both.sum()), 守りを通った数=len(pas), 選び方=how, 答え=row(ans),
                上位5=[row(i) for i in pas[:5]], 両方5ずつの最良=(row(p5[0]) if p5 else None),
                今のmainから10を出す=srcs, 両方を含む天井=row(ceil[0]))


if __name__ == '__main__':
    NO.main(OUT, extra=extra)
    d = json.load(open(OUT))['追加']
    print(json.dumps(dict(数=d['両方を含む形の数'], 通った=d['守りを通った数'], 答え=d['答え']['形'],
                          両方5=(d['両方5ずつの最良'] or {}).get('形')), ensure_ascii=False))
