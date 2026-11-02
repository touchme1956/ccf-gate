#!/usr/bin/env python3
"""night/best15c_posthoc.py — best15c の答えの事後の診断（判定に使わない・2026-11-01・参考・配分は変えない）

best15c（out/best15c_check.json）の答え SMH40/FBT35/ITA20/XLK5 の FBT を XLV に替える・半分ずつ・SMH を30に下げた形を、
同じ物差し（best15_check.Fast・Cent）と同じ条件 T1c（best15c_check.feas）で今と比べ、どの条件で落ちるかを出す。
形は答えを見た後に選んだ（守り寄りに寄せたらどうなるか）＝事後。
使い方: python3 night/best15c_posthoc.py → out/best15c_posthoc.json
"""
import contextlib, io, json, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'best15c_posthoc.json')

FORMS = {'答え SMH40/FBT35/ITA20/XLK5': {'SMH': 40, 'FBT': 35, 'ITA': 20, 'XLK': 5},
         '注文書の形 SMH40/FBT35/ITA20/NASDAQ100 5': {'SMH': 40, 'FBT': 35, 'ITA': 20, 'QQQM': 5},
         'XLV 版 SMH40/XLV35/ITA20/XLK5': {'SMH': 40, 'XLV': 35, 'ITA': 20, 'XLK': 5},
         '半分ずつ SMH40/FBT20/XLV15/ITA20/XLK5': {'SMH': 40, 'FBT': 20, 'XLV': 15, 'ITA': 20, 'XLK': 5},
         'SMH40/FBT25/XLV10/ITA20/XLK5': {'SMH': 40, 'FBT': 25, 'XLV': 10, 'ITA': 20, 'XLK': 5},
         'SMH30/FBT35/ITA25/NASDAQ100 10': {'SMH': 30, 'FBT': 35, 'ITA': 25, 'QQQM': 10},
         'SMH30/FBT30/ITA25/NASDAQ100 15': {'SMH': 30, 'FBT': 30, 'ITA': 25, 'QQQM': 15}}


def main():
    import best15_check as B
    import best15c_check as BC
    import unx_assets as U
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    B.century_extend(U)
    P = BC.POOL
    fast, cent = B.Fast(U, rows, chains, P), B.Cent(U, P)
    F = {'今': dict(B.NOW), **FORMS}
    W = np.array([[f.get(c, 0) for c in P] for f in F.values()], dtype=np.float64)
    e, ce = fast.eval(W), cent.eval(W)
    now = {k: float(v[0]) for k, v in {**e, **ce}.items() if k != 'ok'}
    E = {**e, 'c30med': ce['c30med'], 'c30min': ce['c30min'], 'cok': ce['ok']}
    f, g = BC.feas(E, now)
    out = {}
    for i, nm in enumerate(F):
        out[nm] = dict(形=F[nm], P15π=round(100 * float(e['P15'][i]), 2), 平均=round(100 * float(e['mean_pi'][i]), 2),
                       最悪の世界=round(100 * float(e['worst'][i]), 2), 五パーセント未満=round(100 * float(e['P5'][i]), 2),
                       最大下落=round(100 * float(e['mdd'][i]), 1), 過去の20年=round(100 * float(e['past20'][i]), 1),
                       百年の中央=round(float(ce['c30med'][i]), 3), 百年の最悪=round(float(ce['c30min'][i]), 3),
                       条件=('通る' if f[i] else '通らない'), 落ちた条件=[k for k, v in g.items() if not bool(v[i])])
        print(nm, json.dumps(out[nm], ensure_ascii=False))
    json.dump(dict(generated=time.strftime('%Y-%m-%d'), tool='night/best15c_posthoc.py', kind='事後の診断（判定に使わない）', forms=out),
              open(OUT, 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
