#!/usr/bin/env python3
"""100年の代用で最もよいポートフォリオを総当たりで探す（century_best・参考・判定なし・2026-10-26）

ユーザーの問い「100年で図ると最もよいポートフォリオは？」。物差しは unx_assets.century_monthly（Ken French 49業種の写し・
毎月組み直し・毎月同額の積立の最終額 ÷ 米国株全体に同じく積み立てた最終額・30年は起点1965〜1995・20年は起点1965〜2005）。
新しい物差しは作らない（同じ式を numpy で回すだけ・回帰の検査で century_monthly と一致を確かめる）。

★回す前に固定したこと（このファイルを結果の前にコミット）
  部品（写しのある本だけ）: QQQM（テック65%＋市場35%）・SMH（Chips）・ITA（Aero＋Guns・SHLD も同じ写しなので ITA にまとめる）・
    XLV（Drugs＋MedEq＋Hlth）・FBT（Drugs）・VOO（市場）・GDX（Gold）・XLU（Util）の8本・5%刻み・合計100%（888,030通り）。
  何を「よい」とするか（3つ並べ、1つに決めない）:
    A 平均: 30年の中央値が最大
    B 守り: 30年の最悪の窓が最大
    C 釣り合い: 4つ（30年の中央値・30年の下位10%点・20年の中央値・20年の下位10%点）の百分位の順位の平均が最大
  縛り: (0) なし (1) 1本30%まで (2) NASDAQ100（QQQM）30%以上
  過学習の検査: C を前半の起点（30年 1965〜1979）だけで選んだ形が後半の起点（1980〜1995）でどうだったか、と逆向き。
  参考: 今の形（全体の形＝個別株を席の業種の写しで）・案1（NDX40/SMH30/ITA15/SHLD5/XLV5/FBT5）・案2（NDX50/SMH25/ITA10/SHLD5/XLV5/FBT5）。
  ⚠ 承知の限界: どの業種が100年で勝ったかは後から分かったこと（後知恵）＝勝った業種に寄るのは当然。個別株のぶれ・費用・税・為替は入らない。
"""
import itertools, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import unx_assets as U

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = ['QQQM', 'SMH', 'ITA', 'XLV', 'FBT', 'VOO', 'GDX', 'XLU']
STEP = 5


def grid():
    n, k = 100 // STEP, len(ASSETS)
    for c in itertools.combinations(range(n + k - 1), k - 1):
        prev, w = -1, []
        for x in c:
            w.append(x - prev - 1); prev = x
        w.append(n + k - 2 - prev)
        yield [v * STEP for v in w]


def setup():
    C = U.century_parts()
    F, parts, mkt, endm = C['F'], C['parts'], C['mkt'], C['endm']
    wins = []
    for n, lab, starts in ((360, '30', range(1965, 1996)), (240, '20', range(1965, 2006))):
        for y in starts:
            ms = F.months((y + 1) * 100 + 1, n)
            if ms[-1] > endm:
                continue
            wins.append((lab, y, ms))
    allm = sorted({m for _, _, ms in wins for m in ms})
    idx = {m: i for i, m in enumerate(allm)}
    R = np.array([[parts[a][m] for m in allm] for a in ASSETS])      # 欠けがあれば KeyError で止まる
    M = np.array([mkt[m] for m in allm])
    W = [(lab, y, idx[ms[0]], idx[ms[-1]]) for lab, y, ms in wins]
    return R, M, W, F


def dca(r, W):
    """r: (N, T) 毎月のリターン → 各窓の dca_mult（N, 窓）。V=Σ_t Π_{s=t..e}(1+r_s)"""
    L = np.log1p(r)
    cs = np.concatenate([np.zeros((r.shape[0], 1)), np.cumsum(L, axis=1)], axis=1)
    out = np.empty((r.shape[0], len(W)))
    for j, (_, _, a, e) in enumerate(W):
        seg = cs[:, e + 1:e + 2] - cs[:, a:e + 1]           # Π_{s=t..e} の対数
        out[:, j] = np.exp(seg).sum(axis=1) / (e - a + 1)
    return out


def q10(x):
    n = x.shape[1]
    i = min(n - 1, max(0, int(round(0.10 * (n - 1)))))
    return np.sort(x, axis=1)[:, i]


def stats(ratio, W, sel=None):
    out = {}
    for lab in ('30', '20'):
        js = [j for j, w in enumerate(W) if w[0] == lab and (sel is None or sel(w))]
        if not js:
            continue
        x = ratio[:, js]
        out[lab] = dict(med=np.median(x, axis=1), p10=q10(x), worst=x.min(axis=1), beat=(x > 1).mean(axis=1))
    return out


def main():
    R, M, W, F = setup()
    mk = dca(M[None, :], W)[0]
    combos = np.array(list(grid()), dtype=float)
    res = {k: [] for k in ('m30', 'p30', 'w30', 'b30', 'm20', 'p20', 'w20', 'b20', 'mA', 'mB')}
    for s in range(0, len(combos), 20000):
        Wt = combos[s:s + 20000] / 100
        ratio = dca(Wt @ R, W) / mk
        st = stats(ratio, W)
        for lab in ('30', '20'):
            for k, kk in (('med', 'm'), ('p10', 'p'), ('worst', 'w'), ('beat', 'b')):
                res[kk + lab].append(st[lab][k])
        res['mA'].append(stats(ratio, W, lambda w: w[0] == '30' and w[1] <= 1979)['30']['med'])
        res['mB'].append(stats(ratio, W, lambda w: w[0] == '30' and w[1] >= 1980)['30']['med'])
    res = {k: np.concatenate(v) for k, v in res.items()}

    # 回帰の検査: century_monthly と一致
    chk = {'QQQM': 40, 'SMH': 30, 'ITA': 20, 'XLV': 5, 'FBT': 5}
    ref = U.century_monthly(chk)
    i = int(np.where((combos == np.array([chk.get(a, 0) for a in ASSETS])).all(axis=1))[0][0])
    got = (res['m30'][i], res['w30'][i], res['m20'][i], res['p20'][i])
    exp = (ref['30年の積立（起点1965〜1995）']['_med'], ref['30年の積立（起点1965〜1995）']['最悪'],
           ref['20年の積立（起点1965〜2005）']['_med'], ref['20年の積立（起点1965〜2005）']['_p10'])
    assert all(abs(a - b) < 6e-4 for a, b in zip(got, exp)), (got, exp)

    pr = lambda v: v.argsort().argsort() / (len(v) - 1)
    bal = (pr(res['m30']) + pr(res['p30']) + pr(res['m20']) + pr(res['p20'])) / 4
    mx = combos.max(axis=1)
    cons = {'縛りなし': np.ones(len(combos), bool), '1本30%まで': mx <= 30, 'NASDAQ100 30%以上': combos[:, 0] >= 30}

    def row(i):
        f = {a: int(combos[i][j]) for j, a in enumerate(ASSETS) if combos[i][j] > 0}
        return {'形': f, '30年': {'中央値': round(res['m30'][i], 3), '下位10%点': round(res['p30'][i], 3), '最悪': round(res['w30'][i], 3),
                                 '市場に勝った割合': round(res['b30'][i], 2)},
                '20年': {'中央値': round(res['m20'][i], 3), '下位10%点': round(res['p20'][i], 3), '最悪': round(res['w20'][i], 3),
                         '市場に勝った割合': round(res['b20'][i], 2)},
                '30年の中央値 前半の起点〜1979': round(res['mA'][i], 3), '後半の起点1980〜': round(res['mB'][i], 3)}

    out = {'部品': ASSETS, '刻み': STEP, '通り': len(combos), '結果': {}}
    for cn, ok in cons.items():
        d = {}
        for nm, v in (('A 平均（30年の中央値）', res['m30']), ('B 守り（30年の最悪）', res['w30']), ('C 釣り合い（4つの順位の平均）', bal)):
            vv = np.where(ok, v, -np.inf)
            top = np.argsort(-vv)[:5]
            d[nm] = [row(int(i)) for i in top]
        # 過学習: 前半の起点だけで A を選んだ形の後半
        for nm, a, b in (('前半で選ぶ→後半', 'mA', 'mB'), ('後半で選ぶ→前半', 'mB', 'mA')):
            va = np.where(ok, res[a], -np.inf); i = int(np.argmax(va))
            d[nm] = {'選んだ形': row(i)['形'], '選んだ側の中央値': round(res[a][i], 3), '反対側の中央値': round(res[b][i], 3),
                     '反対側での順位（上位%）': round(100 * (res[b][ok] > res[b][i]).mean(), 1)}
        out['結果'][cn] = d

    ref_forms = {}
    cc, _, _ = U.castle_copy()
    for nm, f in (('今（全体の形）', U.whole({'QQQM': 40, 'SMH': 25, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5}, cc)),
                  ('案1', {'QQQM': 40, 'SMH': 30, 'ITA': 15, 'SHLD': 5, 'XLV': 5, 'FBT': 5}),
                  ('案2', {'QQQM': 50, 'SMH': 25, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5}),
                  ('S&P500 だけ', {'VOO': 100}), ('NASDAQ100 だけ', {'QQQM': 100})):
        ref_forms[nm] = {'形': {k: round(v, 2) for k, v in f.items()}, **U.strip_century(U.century_monthly(f))}
    out['参考'] = ref_forms
    # 1本だけ
    out['1本だけ'] = {a: row(int(np.where(combos[:, j] == 100)[0][0])) for j, a in enumerate(ASSETS)}
    json.dump(out, open(os.path.join(BASE, 'out', 'century_best.json'), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:200])


if __name__ == '__main__':
    main()
