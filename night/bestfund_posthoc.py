#!/usr/bin/env python3
"""night/bestfund_posthoc.py — bestfund の事後の診断（判定には使わない・読むだけ・門・配分には触れない）

事前登録 out/bestfund_prereg.json（d5eab7f）の判定は night/bestfund.py → out/bestfund.json がすべて。
ここは**結果を見た後に**、判定の弱いところを数えるだけ（2026-10-11・ユーザー「時間を使って最高の投資信託かETFを探して…」への私の判断の材料）。
登録と同じ乱数（共通乱数）で回すので、入力を変えた分だけが順位に出る。最初に登録の CE をそのまま再現できるかを確かめる。

  (1) 世界の組を変える: 6つ（登録）／D を外す／B・C・E／B・C だけ
      ＝世界 D の材料（アナリストの長期の伸びの予想）が S&P500 と業種の SPDR にしか無い非対称と、
        FANG+ の約9年の記録が A1・A2・E の3つに入っていることの影響
  (2) λ=0（H4 の業種の β −0.035 を切り詰めた値＝業種・テーマの賭けに当てる相手）と、λ=0 で D を外す
  (3) 世界 E の費用を縮めない（各賭けの費用を全部引く。登録の式は上乗せ X を費用の差を引いた後で作り λ で縮めるので、
      費用の高い賭けほど E で費用が軽くなる——独立の検算の指摘）
  (4) λ を単位ごとに 0〜1 へ切り詰めてから平均（登録は平均の後で切り詰め 0.212・こちらは 0.246）
  (5) 下位の分位（20年積立の年率・6つの世界をまとめた道）

  python3 night/bestfund_posthoc.py   → out/bestfund_posthoc.json（約5分）
"""
import datetime, json, math, os, statistics as S, sys

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import bestfund as B           # noqa: E402
import bestfund_data as D      # noqa: E402

OUT = os.path.join(BASE, 'out', 'bestfund_posthoc.json')
SHOW = ['FANG', 'SP500', 'TECH_SPDR', 'NDX', 'USTOT', 'HEALTH', 'MEGAG', 'HIDIV', 'SMALLV', 'VALUE', 'ACWI']


def world_e_fullcost(ch, cost, bnet, cnet, dnet, lam):
    """世界 E の費用を縮めない版: 地域の市場（費用後）＋ λ×（費用前の上乗せ）−（自分の費用 − 地域の市場の費用）"""
    out = {}
    for b in B.BETS:
        reg = D.region_of(b)
        m = S.mean([bnet[reg], cnet[reg], dnet[reg]])
        if b == reg:
            out[b] = m
            continue
        r, q = B.nat(ch, b), B.nat(ch, reg)
        ks = sorted(k for k in r if k in q)
        x = B.geo(r, ks) - B.geo(q, ks)
        out[b] = m + lam * x - (cost[b] - cost[reg])
    return out


def ranks(sims, elig, worlds, gamma=2):
    sc = {b: B.summarize_bet(sims[b], worlds, gamma)['ce_irr'] for b in elig}
    order = sorted(elig, key=lambda b: -sc[b])
    return {'top8': [(b, round(100 * sc[b], 2)) for b in order[:8]],
            'rank': {b: order.index(b) + 1 for b in SHOW if b in sc},
            'ce': {b: round(100 * sc[b], 2) for b in SHOW if b in sc},
            'gap_1st_2nd': round(100 * (sc[order[0]] - sc[order[1]]), 2)}


def main():
    ch = D.chains()
    cost = B.costs()
    elig = [b for b in B.BETS if D.eligible(b)]
    bg, _ = B.world_b_gross()
    cg = B.world_c_gross(bg)
    dg = B.world_d_gross(cg)
    per = json.load(open(B.PERSIST))
    lam = per['lambda_main']['lambda']
    by_unit = per['lambda_main']['by_unit']
    lam_unit = round(S.mean(min(1.0, max(0.0, v)) for v in by_unit.values()), 3)
    mu, _ = B.worlds_all(ch, cost, bg, cg, dg, lam)
    sz = B.sigma_z(ch)
    sims = B.simulate(mu, sz, B.WORLDS)
    reg = json.load(open(B.OUT))
    regce = {t['bet']: t['CE_γ2(%/年)'] for t in reg['table']}
    base = ranks(sims, elig, B.WORLDS)
    repro = max(abs(round(100 * B.summarize_bet(sims[b], B.WORLDS)['ce_irr'], 2) - regce[b]) for b in elig)
    res = {'generated': datetime.date.today().isoformat(), 'tool': 'night/bestfund_posthoc.py',
           'role': '事後の診断（結果を見た後・判定に使わない）。判定は out/bestfund.json（事前登録 d5eab7f）',
           'reproduces_registered_ce_max_abs_diff_pt': repro, 'variants': {}}
    V = res['variants']
    V['登録どおり（6つの世界）'] = base
    for nm, ws in (('D を外す（A1・A2・B・C・E）', ['A1', 'A2', 'B', 'C', 'E']), ('B・C・E（D と歴史を外す）', ['B', 'C', 'E']),
                   ('B・C だけ（前向きの模型だけ）', ['B', 'C']), ('歴史だけ（A1・A2）', ['A1', 'A2'])):
        V[nm] = ranks(sims, elig, ws)
    del sims
    # λ=0
    mu0, _ = B.worlds_all(ch, cost, bg, cg, dg, 0.0)
    s0 = B.simulate(mu0, sz, B.WORLDS)
    V['λ=0（業種の β を当てる）'] = ranks(s0, elig, B.WORLDS)
    V['λ=0・D を外す'] = ranks(s0, elig, ['A1', 'A2', 'B', 'C', 'E'])
    del s0
    # E の費用を縮めない
    e_full = world_e_fullcost(ch, cost, mu['B'], mu['C'], mu['D'], lam)
    s1 = B.simulate(dict(mu, E=e_full), sz, B.WORLDS)
    V['E の費用を縮めない（各賭けの費用を全部引く）'] = ranks(s1, elig, B.WORLDS)
    V['E の費用を縮めない（各賭けの費用を全部引く）']['E_pct'] = {b: (round(100 * mu['E'][b], 2), round(100 * e_full[b], 2)) for b in SHOW}
    del s1
    # λ を単位ごとに切り詰めてから平均
    mu2, _ = B.worlds_all(ch, cost, bg, cg, dg, lam_unit)
    s2 = B.simulate(mu2, sz, B.WORLDS)
    V[f'λ を単位ごとに切り詰めてから平均（{lam_unit}）'] = ranks(s2, elig, B.WORLDS)
    del s2
    # 下位の分位
    sims = B.simulate(mu, sz, B.WORLDS)
    dn = {}
    for b in ['FANG', 'SP500', 'TECH_SPDR', 'NDX', 'HEALTH', 'ACWI', 'USTOT']:
        pool = np.concatenate([sims[b][w] for w in B.WORLDS])
        dn[b] = {f'p{q}': round(100 * float(B.irr_from_multiple(np.array([np.percentile(pool, q)]))[0]), 2) for q in (1, 5, 10, 25, 50, 75, 90)}
    res['downside_dca20_irr_pct'] = dn
    res['notes'] = ['世界 D の材料（今の PER・長期の PER・配当利回り・アナリストの3〜5年の伸びの予想）が揃ったのは S&P500 と業種の SPDR 6本だけ。他の賭けの D は C と同じ',
                    'FANG+ の A1・A2 は「2017-10〜の S&P500 との差」を S&P500 の A1・A2 に足した値（事前登録の決まり）。E もその9年の上乗せ X から作る',
                    'FANG+ の系列は価格指数（配当なし）＝A1・A2・E が配当（年0.3%前後）の分だけ不利に出ている',
                    '感度は事前登録の外（結果を見た後）。順位を決めるのに使わない']
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT, '登録の CE の再現の最大差', repro)
    for nm, v in V.items():
        print(f'{nm}: 1位と2位の差 {v["gap_1st_2nd"]}  上位 {v["top8"][:5]}')
        print('    順位', v['rank'])


if __name__ == '__main__':
    main()
