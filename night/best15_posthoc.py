#!/usr/bin/env python3
"""night/best15_posthoc.py — best15 の事後の診断（選び方の外・判定に使わない・2026-11-01）

best15_check の答え（T1 SMH40/FBT25/QQQM15/GDX10/ITA5/XLK5）を見たあとに足した参考。best15 の選び方・答えは変えない。
  D1 GDX を入れない場合の T1 の最良（第2段の本から GDX を外して同じ道・同じ門・同じ順位の決め方）
  D2 FBT を15%まで・GDX を入れない場合の T1 の最良（生のバイオ株の比重を抑えた形）
  D3 感度5本ごとの P15π・P5π・π加重の平均・最悪の世界（今・T1 の答え・D1・D2・D4・D5・核4本だけの最良）
  D4・D5 SMH を20%（今と同じ）・30%までに抑えたときの T1 の答え（第1段から同じ手順で探し直す＝候補の選び直しも同じ決まり・
         最終の確かめ F1・F2 も同じ）。10-29 に「半導体30%はやりすぎでは？」で SMH を20%にした経緯を受けて足した
使い方: python3 night/best15_posthoc.py → out/best15_posthoc.json
"""
import io, contextlib, json, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import best15_check as B

OUT = os.path.join(B.BASE, 'out', 'best15_posthoc.json')


def main():
    t0 = time.time()
    B.check_now()
    import unx_assets as U
    import ndx_swap_check as N
    import upside_check as UC
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    pool = B.pool_list()
    B.century_extend(U)
    fast, cent = B.Fast(U, rows, chains, pool), B.Cent(U, pool)
    j = json.load(open(B.OUT))
    assets2 = j['stage2']['本']
    n = len(pool)
    W0 = np.array([[B.NOW.get(c, 0) for c in pool]], dtype=np.float64)
    e0, c0 = fast.eval(W0), cent.eval(W0)
    now = {k: float(v[0]) for k, v in {**e0, **c0}.items() if k != 'ok'}
    assert abs(now['P15'] - j['now_raw']['P15']) < 1e-12, '今の値が best15_check と違う'
    out = {}
    for key, drop, fbt_cap in (('D1 GDX を入れない', {'GDX'}, None), ('D2 GDX を入れない・FBT は15%まで', {'GDX'}, 3)):
        al = [c for c in assets2 if c not in drop]
        A2s = B.all_forms(len(al), B.KMAX, B.CAP)
        if fbt_cap is not None:
            A2s = A2s[A2s[:, al.index('FBT')] <= fbt_cap]
        A = np.zeros((len(A2s), n), dtype=np.int8)
        A[:, [pool.index(c) for c in al]] = A2s
        E = B.run_forms(fast, cent, A, now)
        mk = B.masks(E, now)
        ii = np.where(mk['T1'])[0]
        best = B.order(ii, E, A, pool)[0] if len(ii) else None
        out[key] = dict(本=al, 形の数=int(len(A)), T1を通った形=int(len(ii)),
                        最良=None if best is None else {pool[k]: int(A[best][k]) * B.STEP for k in range(n) if A[best][k] > 0})
        B.log(key, out[key]['最良'], len(ii))
    # D4・D5: SMH の上限つきで第1段から探し直す（best15_check.main と同じ手順・同じ門・同じ順位）
    import ndx_swap_check as N2
    ch_jpy, _ = U.jpy_chains(chains)
    idx_core = [pool.index(c) for c in B.CORE]
    ism = pool.index('SMH')
    capd = {}
    for key, cap_u in (('D4 SMH は20%まで（今と同じ）', 4), ('D5 SMH は30%まで', 6)):
        st1 = {}
        for x in pool:
            if x in B.CORE:
                continue
            A5 = B.all_forms(5, 5, B.CAP, must=4)
            A = np.zeros((len(A5), n), dtype=np.int8)
            A[:, idx_core + [pool.index(x)]] = A5
            A = A[A[:, ism] <= cap_u]
            E = B.run_forms(fast, cent, A, now)
            mk = B.masks(E, now)
            row = {}
            for tr in ('T1', 'T2'):
                ii = np.where(mk[tr])[0]
                row[tr] = None
                if len(ii):
                    b = B.order(ii, E, A, pool)[0]
                    row[tr] = dict(最良の形=B.name_of(A[b], pool), P15π=round(100 * E['P15'][b], 2), 今との差=round(100 * (E['P15'][b] - now['P15']), 2))
            st1[x] = row

        def top(tr):
            c = [(x, r[tr]['今との差']) for x, r in st1.items() if r[tr] and r[tr]['今との差'] > 0]
            return [x for x, _ in sorted(c, key=lambda t: (-t[1], t[0]))[:B.NTOP1]]
        al = list(dict.fromkeys(list(B.CORE) + top('T1') + top('T2')))
        A2s = B.all_forms(len(al), B.KMAX, B.CAP)
        A2s = A2s[A2s[:, al.index('SMH')] <= cap_u]
        A = np.zeros((len(A2s), n), dtype=np.int8)
        A[:, [pool.index(c) for c in al]] = A2s
        E = B.run_forms(fast, cent, A, now)
        mk = B.masks(E, now)
        ii = np.where(mk['T1'])[0]
        lst = B.order(ii, E, A, pool)[:B.NFIN] if len(ii) else []
        fz = {B.name_of(A[i], pool): {pool[k]: int(A[i][k]) * B.STEP for k in range(n) if A[i][k] > 0} for i in lst}
        fc = B.final_check(U, N2, rows, chains, ch_jpy, fz, 'T1')[0] if fz else {}
        ans = next((k for k in fz if fc[k]['F1の合否'] and fc[k]['F2の合否']), None)
        st1_top = {tr: top(tr) for tr in ('T1', 'T2')}
        capd[key] = dict(第1段で選ばれた本=st1_top, 第2段の本=al, 形の数=int(len(A)), T1を通った形=int(len(ii)),
                         答え=fz.get(ans) if ans else '今のまま', 答えの名前=ans,
                         上位=[dict(名前=k, P15π=round(100 * E['P15'][i], 2), 平均=round(100 * E['mean_pi'][i], 2), 最大下落=round(100 * E['mdd'][i], 1),
                                  F1=fc[k]['F1の合否'], F2=fc[k]['F2の合否']) for k, i in zip(fz, lst)][:10],
                         第1段={x: r for x, r in st1.items() if (r['T1'] or r['T2'])})
        out[key] = capd[key]
        B.log(key, capd[key]['答えの名前'], st1_top, len(ii))

    forms = {'今': dict(B.NOW)}
    t1 = j['picks']['T1']
    forms['T1 の答え'] = {k: v for k, v in j['detail']['T1の答え']['形'].items()}
    for key in out:
        f = out[key].get('最良') or (out[key].get('答え') if isinstance(out[key].get('答え'), dict) else None)
        if f:
            forms[key] = f
    s0 = j['stage0']['T1']['最良の形']
    forms['核4本だけの最良'] = {p[:len(p.rstrip('0123456789'))]: int(p[len(p.rstrip('0123456789')):]) for p in s0.split('/')}
    assets = sorted({a for f in forms.values() for a in f} | {'VOO'})
    k4, _ = N.chips_adj(rows, assets)
    vt = N.variants(forms, rows, chains, k4)[UC.W_CRASH]
    mega = U.mega_map(rows, assets)
    tab = U.measure(forms, rows, chains, mega=mega)[UC.W_CRASH]
    d3 = {}
    for nm in forms:
        d3[nm] = {'形': forms[nm],
                  **{N.VARS_JA[v]: {k: round(100 * vt[nm][v][k], 2) for k in ('P15', 'P5', 'mean_pi', 'worst')} for v in N.VARS},
                  '主の表示': {k: tab[nm][k] for k in ('P15π', 'P5π（5%未満）', 'π加重の平均の年率', '最悪の世界', 'ぶれ', '最大下落',
                                                    '過去の転がる20年で15%以上', '積立20年の内部収益率')}}
        cm = U.century_monthly(forms[nm])
        d3[nm]['100年の代用'] = None if cm is None else U.strip_century(cm)
    doc = dict(generated=time.strftime('%Y-%m-%d'), tool='night/best15_posthoc.py', kind='事後の診断（best15 の選び方の外・判定に使わない）',
               base='out/best15_check.json', T1の答え=t1, 探し直し=out, 感度ごと=d3, secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    B.log('完了', doc['secs'], '秒')


if __name__ == '__main__':
    main()
