#!/usr/bin/env python3
"""night/etf_p15_caps.py — 「15%以上の確率を40%にできるか」——バランスの縛りごとに確率の最大を測る（2026-10-10・ユーザー「40%は目指せない？」）

読むだけ。門・採点・配分には触れない。物差しは night/etf_p15.py（20年の毎月の積立の内部収益率≥15% の確率・4つの世界の平均）と
night/etf_forward_combo.py（4つの世界の年率・ぶれ・最大下落）をそのまま使う。組み合わせは 1〜5本・10%刻み（3,116,505通り）。
縛り: 半導体 SMH の上限・1本あたりの上限・テック（NASDAQ100＋XLK＋SMH）の上限・NASDAQ100 の下限（iDeCo・こどもNISA の分）・ぶれが今以下。各縛りで確率が最大の組み合わせ（同点は5%未満の確率が低い→ぶれが低い）。

出力: out/etf_p15_caps.json
"""
import datetime, json, os, sys
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etf_p15 as P   # noqa: E402

OUT = os.path.join(BASE, 'out', 'etf_p15_caps.json')


def main():
    CB = P.CB
    ctx = CB.build(max_k=5)
    C = CB.CANDS
    W, Wint, vol1, mdd1, gbs, worlds, base_of = ctx['W'], ctx['Wint'], ctx['vol1'], ctx['mdd1'], ctx['grid_bs'], ctx['worlds'], ctx['base_of']
    tabs = P.dca_tables(20, [0.05, 0.15], log=False)
    names = ['A1', 'A2', 'B', 'C']
    wv = worlds(W, gbs, 'main')
    s = np.sqrt(gbs['q1'])
    per = {n: P.interp(tabs[0.15], np.log1p(wv[n]), s) for n in names}
    p15 = np.mean([per[n] for n in names], axis=0)
    p5 = 1 - np.mean([P.interp(tabs[0.05], np.log1p(wv[n]), s) for n in names], axis=0)
    wnow = np.array([[{'QQQM': 50 / 85, 'XLK': 15 / 85, 'SMH': 20 / 85}.get(c, 0.0) for c in C]])
    v_now = float(base_of(wnow)['vol'][0])
    j = {c: C.index(c) for c in C}
    smh = Wint[:, j['SMH']].astype(int) * 10
    mx = Wint.max(axis=1).astype(int) * 10
    tech = (Wint[:, j['SMH']].astype(int) + Wint[:, j['QQQM']].astype(int) + Wint[:, j['XLK']].astype(int)) * 10

    def best(mask):
        ids = np.where(mask)[0]
        if len(ids) == 0:
            return None
        i = int(ids[np.lexsort((vol1[ids], p5[ids], -p15[ids]))[0]])
        return dict(weights={C[k]: int(Wint[i, k]) * 10 for k in np.argsort(-Wint[i].astype(int), kind='stable') if Wint[i, k]},
                    確率=round(100 * float(p15[i]), 1), 世界ごと={n: round(100 * float(per[n][i]), 1) for n in names},
                    五未満=round(100 * float(p5[i]), 1), 平均=round(100 * float(wv['mean'][i]), 2), 最悪=round(100 * float(wv['worst'][i]), 2),
                    ぶれ=round(100 * float(vol1[i]), 1), 最大下落=round(100 * float(mdd1[i]), 1))
    allm = np.ones(len(W), bool)
    lowv = vol1 <= v_now
    res = {'SMHの上限ごと': {}, 'SMHの上限ごと_ぶれが今以下': {}, '1本の上限ごと': {}, 'テックの上限ごと': {}, 'NASDAQ100の下限ごと': {}}
    ndx = Wint[:, j['QQQM']].astype(int) * 10
    for cap in (0, 10, 20, 30, 40, 50, 60, 70, 80, 100):
        res['SMHの上限ごと'][f'SMH≤{cap}%'] = best(smh <= cap)
        res['SMHの上限ごと_ぶれが今以下'][f'SMH≤{cap}%'] = best((smh <= cap) & lowv)
    for cap in (20, 30, 40, 50, 60, 100):
        res['1本の上限ごと'][f'1本≤{cap}%'] = best(mx <= cap)
    for cap in (30, 40, 50, 60, 70, 100):
        res['テックの上限ごと'][f'テック≤{cap}%'] = best(tech <= cap)
    # 2027-01 から iDeCo とこどもNISA の月6万円（入金20万円の3割）が NASDAQ100 に自動で入る＝NASDAQ100 は少なくとも3割前後残る
    for fl in (30, 40, 50):
        res['NASDAQ100の下限ごと'][f'NASDAQ100≥{fl}%'] = best(ndx >= fl)
        res['NASDAQ100の下限ごと'][f'NASDAQ100≥{fl}%・1本≤40%'] = best((ndx >= fl) & (mx <= 40))
    n40 = int((p15 >= 0.40).sum())
    min_smh_40 = int(smh[p15 >= 0.40].min()) if n40 else None
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/etf_p15_caps.py',
               question='15%以上の確率（20年の積立・4つの世界の平均）をバランスの縛りの下でどこまで上げられるか',
               now_vol=round(100 * v_now, 1), n_combos=int(len(W)),
               確率40以上の組み合わせの数=n40, 確率40以上の中のSMHの最小=min_smh_40,
               確率40以上でSMHが最小の組み合わせ=best((p15 >= 0.40) & (smh == min_smh_40)) if n40 else None,
               results=res,
               note='確率は 4つの世界（直近26年・直近15年・100年の平均・JPM）を同じ重みと置いた仮定の上の数字。毎月を独立な正規分布と置いた。個別株の15%は外')
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print(f'→ {OUT}')
    for grp, d in res.items():
        print(f'■ {grp}')
        for k, b in d.items():
            if b:
                w = ' '.join(f'{a}{x}' for a, x in b['weights'].items())
                print(f"  {k:<10} {w:<34} 確率{b['確率']:5.1f} 5%未満{b['五未満']:5.1f} 最悪{b['最悪']:5.2f} ぶれ{b['ぶれ']:5.1f} 下落{b['最大下落']:6.1f} {b['世界ごと']}")
    print('確率40%以上の組み合わせ', n40, ' その中の SMH の最小', min_smh_40, doc['確率40以上でSMHが最小の組み合わせ'])


if __name__ == '__main__':
    main()
