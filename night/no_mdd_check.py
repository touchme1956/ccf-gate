#!/usr/bin/env python3
"""night/no_mdd_check.py — 最大下落を無視するならどの形か（2026-11-25・参考・配分は変えない）

ユーザー「最大下落を無視するならどのポートフォリオになる？」
読み方（固定）: 同じ日の最適解の探し（night/ndx40_opt_check.py・書庫:22273）と同じ範囲（NASDAQ100 40〜50 ＝ユーザーの条件・
  SMH 15〜35・ITA/FBT 5〜20・VBR/XLV/XLP/XLU 0〜20・2,684形）・同じ物差し・直したデータで、守りの5つから
  最大下落（ドル・円）の2つだけを外す。残す守りは ③年5%未満の確率・⑥業種の基礎率の平均・⑨100年の代用の30年の最悪（V1）。
★選び方はこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする。
  見たもの: ndx40_opt_check の出力（答え＝今の main・守りを全部外した天井 40/SMH35/ITA5/FBT20 年15%以上 29.49・
    年5%未満 20.24・基礎率 8.22・100年の最悪 1.269＝どれも今より悪い）。最大下落だけを外した場合の数字は見ていない。
選び方: 残す守りの3つを今の main より悪くしない形のうち、年15%以上の確率が最も高い形（並べ方は ndx40_opt_check と同じ）。
併せて出す（答えを決めるのに使わない）: 上位5／その形の最大下落・集中／守りを全部外した天井（再掲）。
使い方: python3 night/no_mdd_check.py → out/no_mdd_check.json（約15秒）
"""
import os, sys, json
import numpy as np
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import ndx40_opt_check as NO  # noqa: E402

OUT = os.path.join(BASE, 'out', 'no_mdd_check.json')
KEEP = [2, 5, 8]


def extra(c):
    Y, meas, order, row, yM, EPS = (c[k] for k in ('Y', 'meas', 'order', 'row', 'yM', 'EPS'))
    cond = np.ones(len(Y), dtype=bool)
    for k in KEEP:
        cond &= Y[:, k] >= yM[k] - EPS
    pas = order(cond)
    return dict(残す守り=['③年5%未満の確率', '⑥基礎率の平均', '⑨100年の30年の最悪(V1)'], 守りを通った数=len(pas),
                答え=row(pas[0]), 上位5=[row(i) for i in pas[:5]])


if __name__ == '__main__':
    NO.main(OUT, extra=extra)
    d = json.load(open(OUT))['追加']
    print(json.dumps(dict(通った=d['守りを通った数'], 答え=d['答え']['形']), ensure_ascii=False))
