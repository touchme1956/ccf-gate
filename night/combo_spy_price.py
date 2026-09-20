#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""night/combo_spy_price.py — **探索の値札は何が払っているのか**／**規則を年次で貼り替える形**
（2026-09-19新設・combo_spy の「探索空間の穴」を測る第二の器）

★判定を持たない。事前登録(out/combo_spy_prereg.json)は書き換えていない。門にも触らない（絶対のルール1）。

【問1】家族の帰無95%点 +18.8pt は、候補空間の**どこ**が払っているのか
  別実装の実測が既に「NVDA 1社を抜くと 95%点が +19.0 → +10.9pt」と出している。
  ＝帰無の高さは **小さい群が1社の大当たりを掴む確率**で決まっている疑いがある。
  なら **最小銘柄数を上げると値札は下がる**はずで、それは規則の形の選択そのもの。
  ⚠ これは「線を緩める」話ではない——**同じ線(基準1)を、群の大きさ別に測り直す**だけ。
     観測側も同じ制限を掛ける（片方だけ動かすのは反則）。

【問2】combo_spy は **2013年の順位で買って13年持つ**形しか探していない。
  実際の運用は年次で貼り替える。指標の在庫があるアンカー(2013/2016/2017/2018)で
  **順位を作り直して繋ぐ**形を試す。⚠ 各区間の指標はその年の在庫だけで作る＝look-ahead を持ち込まない。

使い方: python3 night/combo_spy_price.py [--B 300] [--json]
出力  : out/combo_spy_price.json
"""
import json, os, sys, random, datetime as dt
from itertools import combinations

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import combo_spy as C
from combo_spy_shapes import ranks, _signs, as_w, dedupe, family_null_w, wexcess

OUT = os.path.join(BASE, 'out')
SEED = 20260919
SEARCH = '2013'

def main():
    a = sys.argv[1:]
    B = int(a[a.index('--B')+1]) if '--B' in a else 300
    pan = C.panel(); spy = {int(k): v for k, v in C.L('_spy_monthly.json').items()}
    END = max(spy); SEMI = C.semi_set()
    k0 = int(SEARCH)*12+6; months = END-k0
    pool = C.anchor_pool(pan, k0, END); D = C.load_anchor(SEARCH)
    at = C.atoms(SEARCH, pool, D, SEMI)
    M = C.mults(pan, pool, k0, END); spym = spy[END]/spy[k0]
    cands = C.build_cands(at, 3)
    res = {'generated': dt.date.today().isoformat(), 'tool': 'night/combo_spy_price.py',
           'stance': '★測定器。事前登録は書き換えていない。門にも触らない（絶対のルール1）',
           'B': B, 'pool_n': len(pool), 'spy_cagr': round(C.cagr(spym, months), 4)}

    # ── 問1: 最小銘柄数ごとに「値札」と「観測の最良」を測り直す ──────────────
    # ⚠ 観測も帰無も **同じ制限**を掛ける。片方だけ動かすのは反則。
    rows = []
    for mn in (20, 25, 30, 40, 50, 75, 100, 150):
        fam_c = [(n, g) for n, g in cands if len(g) >= mn]
        if len(fam_c) < 20: continue
        sc = sorted(((C.excess(g, M, spym, months), n, len(g)) for n, g in fam_c), reverse=True)
        fam = C.family_null(fam_c, M, spym and spym or 1, months, B, SEED) if False else \
              C.family_null(fam_c, M, pool, spym, months, B, SEED)
        rows.append(dict(min_n=mn, n_cands=len(fam_c), best=round(sc[0][0], 4),
                         best_rule=sc[0][1], best_n=sc[0][2], p95=fam['p95'], med=fam['med'],
                         beats=bool(sc[0][0] > fam['p95']),
                         n_beats=sum(1 for e, _, _ in sc if e > fam['p95'])))
    res['price_by_min_n'] = rows

    # ── 問1b: 値札を払っているのは誰か。上位の勝者を抜いて帰無を測り直す ───────
    # ⚠ **事後の選択**（結果を見てから抜く）なので、これは「発見」ではなく **値札の分解**。
    tot_rank = sorted(M, key=lambda t: -M[t])
    fam_c = [(n, g) for n, g in cands if len(g) >= 20]
    dec = []
    for drop in (0, 1, 3, 5, 10):
        rm = set(tot_rank[:drop])
        pl2 = [t for t in pool if t not in rm]
        c2 = [(n, {t for t in g if t not in rm}) for n, g in fam_c]
        c2 = [(n, g) for n, g in c2 if len(g) >= 20]
        M2 = {t: M[t] for t in pl2}
        fam = C.family_null(c2, M2, pl2, spym, months, B, SEED)
        sc = sorted(((C.excess(g, M2, spym, months), n, len(g)) for n, g in c2), reverse=True)
        dec.append(dict(dropped=drop, names=tot_rank[:drop], n_cands=len(c2),
                        p95=fam['p95'], best=round(sc[0][0], 4),
                        n_beats=sum(1 for e, _, _ in sc if e > fam['p95'])))
    res['price_decomposition_drop_top_winners'] = {
        'note': ('★事後の選択なので「発見」ではない。**値札の中身の分解**。'
                 '別実装の実測「NVDAを抜くと95%点 +19.0→+10.9」を独立に再現できるかを見る'),
        'rows': dec}

    # ── 問2: 年次で順位を貼り替える形 ─────────────────────────────
    # 指標の在庫があるのは 2013/2016/2017/2018。区間ごとにその年の在庫で順位を作り直す。
    LEGS = [('2013', 2013*12+6, 2016*12+6), ('2016', 2016*12+6, 2017*12+6),
            ('2017', 2017*12+6, 2018*12+6), ('2018', 2018*12+6, END)]
    def feats_at(y, pl):
        Dy = C.load_anchor(y); F = {}
        for k in C.FEAT_KEYS:
            m = {t: Dy['feat'][t][k] for t in pl
                 if t in Dy['feat'] and isinstance(Dy['feat'][t].get(k), (int, float))}
            if len(m) >= 200: F[k] = m
        return F
    # 全区間で使える指標だけ（片方の区間で無い指標を『あることにしない』）
    legpools = {y: C.anchor_pool(pan, a0, a1) for y, a0, a1 in LEGS}
    legfeats = {y: feats_at(y, legpools[y]) for y, _, _ in LEGS}
    common = set(legfeats['2013'])
    for y in legfeats: common &= set(legfeats[y])
    common = sorted(common)
    res['refresh_common_feats'] = common
    res['refresh_legs'] = [{'y': y, 'from': a0, 'to': a1, 'months': a1-a0, 'pool': len(legpools[y])}
                           for y, a0, a1 in LEGS]

    def refresh_mult(cb, signs, N):
        """各区間の初めに順位を作り直し、上位N社を等ウェイトで持つ。⚠ 区間ごとに順位は
        その年の在庫だけで作る。区間の終わりで全部売って次の区間の上位Nへ入れ替える。"""
        tot = 1.0; ns = []
        for y, a0, a1 in LEGS:
            pl = legpools[y]; F = legfeats[y]
            R = {c: ranks(F[c], pl) for c in cb}
            have = set(R[cb[0]])
            for c in cb[1:]: have &= set(R[c])
            if len(have) < N: return None, None
            sc = {t: sum(sg*(R[c][t]-.5) for c, sg in zip(cb, signs)) for t in have}
            g = sorted(have, key=lambda t: -sc[t])[:N]
            vals = [pan[t][a1]/pan[t][a0] for t in g if a0 in pan[t] and a1 in pan[t]]
            if len(vals) < N*0.8: return None, None
            tot *= sum(vals)/len(vals); ns.append(len(vals))
        return tot, ns

    rc = []
    for k in (1, 2):
        for cb in combinations(common, k):
            for signs in _signs(k):
                for N in (20, 30, 50, 100):
                    tot, ns = refresh_mult(cb, signs, N)
                    if tot is None: continue
                    e = C.cagr(tot, months) - C.cagr(spym, months)
                    nm = ' + '.join(('' if s > 0 else '−')+c for c, s in zip(cb, signs))
                    rc.append(dict(rule=f'年次貼替 上位{N}: {nm}', N=N, excess=round(e, 4), legs=ns))
    rc.sort(key=lambda r: -r['excess'])
    res['refresh_n_candidates'] = len(rc)
    res['refresh_top10'] = rc[:10]
    res['refresh_bottom5'] = rc[-5:]

    # 年次貼替の帰無: **各区間の中でリターンをシャッフル**する（区間ごとに独立）
    # ⚠ 買い持ちの帰無（1回シャッフル）とは別物。区間をまたいで同じ社が同じ運を持たない形にする。
    if rc:
        legvals = {}
        for y, a0, a1 in LEGS:
            pl = [t for t in legpools[y] if a0 in pan[t] and a1 in pan[t]]
            legvals[y] = (pl, [pan[t][a1]/pan[t][a0] for t in pl])
        # 候補の「各区間で買う社の位置」を先に固定
        packed = []
        for k in (1, 2):
            for cb in combinations(common, k):
                for signs in _signs(k):
                    for N in (20, 30, 50, 100):
                        idxs = []
                        ok = True
                        for y, a0, a1 in LEGS:
                            pl, _ = legvals[y]; F = legfeats[y]
                            R = {c: ranks(F[c], legpools[y]) for c in cb}
                            have = set(R[cb[0]])
                            for c in cb[1:]: have &= set(R[c])
                            have &= set(pl)
                            if len(have) < N: ok = False; break
                            sc = {t: sum(sg*(R[c][t]-.5) for c, sg in zip(cb, signs)) for t in have}
                            g = sorted(have, key=lambda t: -sc[t])[:N]
                            pos = {t: i for i, t in enumerate(pl)}
                            idxs.append([pos[t] for t in g])
                        if ok: packed.append(idxs)
        rnd = random.Random(SEED); mx = []
        base = C.cagr(spym, months)
        keys = [y for y, _, _ in LEGS]
        for _ in range(B):
            sh = {}
            for y in keys:
                v = list(legvals[y][1]); rnd.shuffle(v); sh[y] = v
            best = -9.0
            for idxs in packed:
                tot = 1.0
                for j, y in enumerate(keys):
                    v = sh[y]; ii = idxs[j]
                    tot *= sum(v[i] for i in ii)/len(ii)
                e = C.cagr(tot, months) - base
                if e > best: best = e
            mx.append(best)
        mx.sort()
        res['refresh_family_null'] = dict(B=B, p95=round(mx[int(.95*B)], 4),
                                          med=round(mx[len(mx)//2], 4), max=round(mx[-1], 4),
                                          n_cands=len(packed))
        p95 = res['refresh_family_null']['p95']
        res['refresh_beats_family'] = sum(1 for r in rc if r['excess'] > p95)

    with open(os.path.join(OUT, 'combo_spy_price.json'), 'w') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    if '--json' in a: print(json.dumps(res, ensure_ascii=False, indent=1)); return
    print(f"母集団 {res['pool_n']}／SPY {res['spy_cagr']*100:+.1f}%／B={B}")
    print(f"\n■ 問1 最小銘柄数ごとの値札（観測も帰無も同じ制限）")
    print(f"{'min_n':>6}{'候補':>8}{'観測最良':>10}{'家族95%':>10}{'中央':>9}  超えた")
    for r in res['price_by_min_n']:
        print(f"{r['min_n']:>6}{r['n_cands']:>8}{r['best']*100:>+9.1f}pt{r['p95']*100:>+9.1f}"
              f"{r['med']*100:>+9.1f}   {r['n_beats']}{'  ★' if r['beats'] else ''}")
        print(f"        最良: {r['best_rule'][:70]} (n={r['best_n']})")
    print(f"\n■ 問1b 値札の分解（★事後の選択＝発見ではない）")
    for r in res['price_decomposition_drop_top_winners']['rows']:
        print(f"   上位{r['dropped']}社を抜く {str(r['names'])[:40]:<42} 95%点 {r['p95']*100:+.1f}pt"
              f"  観測最良 {r['best']*100:+.1f}pt  超えた {r['n_beats']}本")
    print(f"\n■ 問2 年次で順位を貼り替える形（{len(common)}指標が全区間で使える）")
    fn = res.get('refresh_family_null')
    if fn: print(f"   候補 {res['refresh_n_candidates']}本  家族95%点 {fn['p95']*100:+.1f}pt"
                 f"（中央 {fn['med']*100:+.1f}）  超えた {res['refresh_beats_family']}本")
    for r in res['refresh_top10'][:8]:
        print(f"   {r['excess']*100:+6.1f}pt  {r['rule'][:66]}  区間n={r['legs']}")

if __name__ == '__main__':
    main()
