#!/usr/bin/env python3
"""night/orukan_check.py — 「NASDAQ100 40 / SMH 25 / ITA 10 / FBT 10 / S&P500 10 / オルカン 5」を今の main と比べる（2026-11-25・参考・配分は変えない）

オルカン（eMAXIS Slim 全世界株式）の代わりに同じ指数（MSCI ACWI）の VT を使う。VT は best15 の物差し（Fast・33本）には入っているが、
業種の基礎率（best15r の FastBR・SEC の SIC で米国の会社しか読めない）と100年の代用（century_extend）の写しが無い。
★だから form_eval の13のうち測れるものだけで比べる（測れない物差しは「測れない」と書き、0や推測で埋めない）。結果を見る前にコミットする。
測る物差し（form_eval と同じ式）: ①期待の年率 ②年15%以上 ③年5%未満 ④最大下落（ドル・崩れあり）⑤最悪の世界の年率 円の最大下落 ⑩実績の年率の中央 ⑪実績の年15%以上の割合。
形（ETF の中の比）: 今の main 40/25/15/10/VBR10・案 40/25/ITA10/FBT10/VOO10/VT5・参考 前の問いの 40/25/15/10/VOO10。
回帰の検査: 今の main と参考の値が out/form_eval_vbr_to_voo.json の V1 と表示の桁で一致（同じ式で測っている確かめ）。
読み方: 測れた物差しがすべて今の main 以上なら「測れた範囲では上」、どれかが下なら「今の main のまま」と答え、上と下を数字で添える。
使い方: python3 night/orukan_check.py → out/orukan_check.json
"""
import contextlib, io, json, os, sys
import numpy as np
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import best15_check as B  # noqa: E402
from five_mix_ndx_check import realized  # noqa: E402
import unx_assets as U  # noqa: E402

FORMS = {'今の main 40/25/15/10/10': {'QQQM': 40, 'SMH': 25, 'ITA': 15, 'FBT': 10, 'VBR': 10},
         '案 40/25/ITA10/FBT10/VOO10/オルカン5': {'QQQM': 40, 'SMH': 25, 'ITA': 10, 'FBT': 10, 'VOO': 10, 'VT': 5},
         '参考 40/25/15/10/VOO10': {'QQQM': 40, 'SMH': 25, 'ITA': 15, 'FBT': 10, 'VOO': 10}}
REF = {'今の main 40/25/15/10/10': '今の main 40/25/15/10/10', '参考 40/25/15/10/VOO10': '案 40/25/15/10/VOO10'}
KEYS = ['①期待の年率', '②年15%以上の確率', '③年5%未満の確率', '④最大下落', '⑤最悪の世界の年率', '⑩実績の年率の中央', '⑪実績の年15%以上の割合']


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    P = B.pool_list()
    fast = B.Fast(U, rows, chains, P)
    chj, _ = U.jpy_chains(chains)
    fastJ = B.Fast(U, rows, chj, P)
    W = np.array([[f.get(c, 0) for c in P] for f in FORMS.values()], dtype=float)
    e, ej, rz = fast.eval(W), fastJ.eval(W), realized(W, fast)
    out = {}
    for i, k in enumerate(FORMS):
        out[k] = {'①期待の年率': round(100 * e['mean_pi'][i], 2), '②年15%以上の確率': round(100 * e['P15'][i], 2),
                  '③年5%未満の確率': round(100 * e['P5'][i], 2), '④最大下落': round(100 * e['mdd'][i], 1),
                  '⑤最悪の世界の年率': round(100 * e['worst'][i], 2), '円の最大下落': round(100 * ej['mdd'][i], 1),
                  '⑩実績の年率の中央': round(100 * rz['med'][i], 2), '⑪実績の年15%以上の割合': round(100 * e['past20'][i], 1)}
    ref = json.load(open(os.path.join(BASE, 'out', 'form_eval_vbr_to_voo.json')))['形ごと']
    bad = []
    for k, rk in REF.items():
        m = ref[rk]['物差し13']['V1']
        for x in KEYS:
            if abs(out[k][x] - m[x]) > 0.011:
                bad.append((k, x, out[k][x], m[x]))
        if abs(out[k]['円の最大下落'] - ref[rk]['円']['最大下落']) > 0.11:
            bad.append((k, '円', out[k]['円の最大下落'], ref[rk]['円']['最大下落']))
    if bad:
        raise SystemExit(f'回帰の検査が通らない: {bad}')
    a, m = out['案 40/25/ITA10/FBT10/VOO10/オルカン5'], out['今の main 40/25/15/10/10']
    sign = {'③年5%未満の確率': -1}
    up = [x for x in KEYS + ['円の最大下落'] if sign.get(x, 1) * (a[x] - m[x]) > 1e-9]
    dn = [x for x in KEYS + ['円の最大下落'] if sign.get(x, 1) * (a[x] - m[x]) < -1e-9]
    res = dict(generated='2026-11-25', tool='night/orukan_check.py', kind='参考（配分は変えない）',
               測れない=['⑥⑦業種の基礎率（VT の中身の業種を SIC で読めない）', '⑧⑨100年の代用（VT の写しが無い）', '⑫⑬集中（VT の中身の一覧が上位41社だけ）'],
               形ごと=out, 案が上=up, 案が下=dn, 読み=('測れた範囲では上' if not dn else '今の main のまま'), 回帰='通過')
    json.dump(res, open(os.path.join(BASE, 'out', 'orukan_check.json'), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
