#!/usr/bin/env python3
"""night/etf_ita_xlk.py — 「ITAとXLKを入れる価値はある？」（2026-10-10・ユーザーの問い）

読むだけ。門・採点・配分には触れない。4つの世界の年率・15%以上の確率・過去の転がる窓は
night/etf_forward_combo.py の build() と night/etf_p15.py をそのまま使う（同じ種・同じ格子＝同じ数字が出る）。

比べ方（このファイルを回す前にコミットして固定した）:
  「X を入れた形」と「同じ重みを NASDAQ100（QQQM）に回した形」の差 Δ ＝ X − NASDAQ100。
  席（X に与える重み・ほかは固定・ETF側の中で割合に直す）:
    A  今の形のその他15%      … NASDAQ100 50 / SMH 20 / X 15                                   （ITA・XLK）
    B1 私の案の ITA の席10    … NASDAQ100 30 / SMH 20 / XLE 10 / VBR 10 / 金 5 / X 10           （ITA）
    B2 私の案に足すなら       … NASDAQ100 20 / SMH 20 / ITA 10 / XLE 10 / VBR 10 / 金 5 / X 10   （XLK。X＝NASDAQ100 なら私の案そのもの）
    C  15%狙いの相棒          … SMH 60 / X 40                                                   （ITA・XLK）
  物差し: 4つの世界の平均・最悪の世界・15%以上の確率（20年の毎月の積立）・5%未満の確率・ぶれ・最大下落（ぶれと最大下落は A1 の実績）。
          過去の転がる20年/15年で15%以上だった割合は参考（判定に使わない）
  判定（各席・各感度。Δ は %pt）:
    価値あり   … Δ平均≥+0.10 かつ Δ最悪≥+0.10 かつ Δぶれ≤+0.5 かつ Δ確率≥−1.0
    価値なし   … Δ平均≤0 かつ Δ最悪≤0
    差が小さい … |Δ平均|<0.10 かつ |Δ最悪|<0.10 かつ |Δぶれ|<1.0
    前提しだい … 上のどれでもない（上から順に当てる）
  感度5本: 主・A2を外す（S2）・半導体の基礎率で割り引く（K4）・B・Cで分散の上乗せなし（K1）・共分散をA2の窓から（K2）
  まとめ: 主が『価値あり』で5本中4本以上が『価値あり』→ 堅い価値あり
          主が『価値なし』か『差が小さい』で5本中4本以上がそのどちらか → 堅い価値なし〜小さい
          それ以外 → 前提しだい
  ⚠ 席Aの主の数字は etf_forward_combo の other15 の表で既に見ていた（ITA 12.21/7.63・XLK 12.07/7.38・NASDAQ100 11.96/7.35）。
    決まりはその後に書いた＝席Aの主は盲検ではない。席B1・B2・C と感度は回す前に見ていない
  あわせて（判定に使わない）: 21本すべてを各席に入れた順位（平均・最悪・確率）・相関（A1・A2 の窓）・中身の重なり・
    年ごとのリターン（テックが下げた年）・最大下落の時期・直近の年率

出力: out/etf_ita_xlk.json
"""
import datetime, json, math, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etf_p15 as P   # noqa: E402

CB = P.CB
OUT = os.path.join(BASE, 'out', 'etf_ita_xlk.json')
VARS = ['main', 'S2', 'K4', 'K1', 'K2']
VARS_JA = {'main': '主', 'S2': 'A2を外す', 'K4': '半導体の基礎率で割り引く', 'K1': 'B・Cで分散の上乗せなし', 'K2': '共分散をA2の窓から'}
SLOTS = {
    'A': dict(ja='今の形のその他15%', base={'QQQM': 50, 'SMH': 20}, slot=15, targets=['ITA', 'XLK']),
    'B1': dict(ja='私の案の ITA の席10', base={'QQQM': 30, 'SMH': 20, 'XLE': 10, 'VBR': 10, 'GLDM': 5}, slot=10, targets=['ITA']),
    'B2': dict(ja='私の案に NASDAQ100 から10を足すなら', base={'QQQM': 20, 'SMH': 20, 'ITA': 10, 'XLE': 10, 'VBR': 10, 'GLDM': 5}, slot=10, targets=['XLK']),
    'C': dict(ja='15%狙いの相棒（SMH 60 / X 40）', base={'SMH': 60}, slot=40, targets=['ITA', 'XLK']),
}
PEERS = ['QQQM', 'XLK', 'SMH', 'VOO', 'ITA', 'XLE', 'VBR', 'VTV', 'XLV', 'GLDM', 'TOPIX']
SHOW = ['ITA', 'XLK', 'QQQM', 'SMH', 'VOO', 'XLE']
YEARS = [2001, 2002, 2008, 2011, 2015, 2018, 2020, 2022, 2025, 2026]
CASTLE = ['CW', 'LRCX', 'MSFT', 'ASML', 'MCO', 'IDXX', 'KLAC', 'GOOGL', 'GOOG', 'TDG']   # 投下可8社と門外例外だった TDG


def verdict(d):
    dm, dw, dv, dp = d['平均'], d['最悪'], d['ぶれ'], d['確率']
    if dm >= 0.10 and dw >= 0.10 and dv <= 0.5 and dp >= -1.0:
        return '価値あり'
    if dm <= 0 and dw <= 0:
        return '価値なし'
    if abs(dm) < 0.10 and abs(dw) < 0.10 and abs(dv) < 1.0:
        return '差が小さい'
    return '前提しだい'


def summarize(vs):
    main_v, others = vs['main'], [vs[k] for k in VARS[1:]]
    if main_v == '価値あり' and sum(o == '価値あり' for o in others) >= 3:
        return '堅い価値あり'
    neg = {'価値なし', '差が小さい'}
    if main_v in neg and sum(o in neg for o in others) >= 3:
        return '堅い価値なし〜小さい'
    return '前提しだい'


def main():
    t0 = time.time()
    ctx = CB.build(max_k=1)                      # 名前のある形だけを測るので組み合わせの格子は1本ずつで足りる
    C = CB.CANDS
    rows, chains = ctx['rows'], ctx['chains']
    base_of, worlds = ctx['base_of'], ctx['worlds']
    G1, adj, T1 = ctx['G1'], ctx['adj'], ctx['T1']
    print(f'データ（{time.time() - t0:.0f}秒）', flush=True)

    # ── 席ごとの形（21本すべてを X に） ──
    forms, keys = [], []
    for sk, sd in SLOTS.items():
        for x in C:
            w = dict(sd['base'])
            w[x] = w.get(x, 0) + sd['slot']
            tot = sum(w.values())
            forms.append([w.get(c, 0) / tot for c in C])
            keys.append((sk, x))
    Wf = np.array(forms)
    bs = base_of(Wf)
    tabs = P.dca_tables(20, [0.05, 0.15], log=False)
    print(f'積立の表（{time.time() - t0:.0f}秒）', flush=True)
    hs = P.hist_success(Wf, G1, adj, T1)

    met = {}
    for var in VARS:
        wv = worlds(Wf, bs, var)
        sig = np.sqrt(bs['q2'] if var == 'K2' else bs['q1'])
        names = wv['names']
        p15 = np.mean([P.interp(tabs[0.15], np.log1p(wv[nm]), sig) for nm in names], axis=0)
        p5 = 1 - np.mean([P.interp(tabs[0.05], np.log1p(wv[nm]), sig) for nm in names], axis=0)
        met[var] = dict(mean=wv['mean'], worst=wv['worst'], p15=p15, p5=p5, wv=wv, names=names)
    vol, mdd = bs['vol'], bs['mdd']

    def row(i, var='main'):
        m = met[var]
        d = dict(平均=round(100 * float(m['mean'][i]), 2), 最悪=round(100 * float(m['worst'][i]), 2),
                 確率=round(100 * float(m['p15'][i]), 1), 五未満=round(100 * float(m['p5'][i]), 1),
                 ぶれ=round(100 * float(vol[i]), 1), 最大下落=round(100 * float(mdd[i]), 1))
        if var == 'main':
            d['世界ごと'] = {nm: round(100 * float(m['wv'][nm][i]), 2) for nm in ('A1', 'A2', 'B', 'C')}
            d['過去20年で15%以上'] = round(100 * float(hs[240][i]), 1)
            d['過去15年で15%以上'] = round(100 * float(hs[180][i]), 1)
        return d

    def delta(i, j, var):
        """i（X）− j（NASDAQ100）。丸める前の値で"""
        m = met[var]
        return dict(平均=100 * float(m['mean'][i] - m['mean'][j]), 最悪=100 * float(m['worst'][i] - m['worst'][j]),
                    確率=100 * float(m['p15'][i] - m['p15'][j]), 五未満=100 * float(m['p5'][i] - m['p5'][j]),
                    ぶれ=100 * float(vol[i] - vol[j]), 最大下落=100 * float(mdd[i] - mdd[j]))

    idx = {k: n for n, k in enumerate(keys)}
    slots_out, verdicts = {}, {}
    for sk, sd in SLOTS.items():
        ii = [idx[(sk, x)] for x in C]
        mm = met['main']
        order = {lab: [C[ii.index(i)] for i in sorted(ii, key=lambda i: -float(mm[key][i]))] for lab, key in (('平均', 'mean'), ('最悪', 'worst'), ('確率', 'p15'))}
        table = {x: row(idx[(sk, x)]) for x in C}
        ent = dict(ja=sd['ja'], base=sd['base'], slot=sd['slot'], table=table,
                   順位={x: {lab: order[lab].index(x) + 1 for lab in order} for x in C},
                   上位3={lab: order[lab][:3] for lab in order}, 判定={})
        j = idx[(sk, 'QQQM')]
        for x in sd['targets']:
            i = idx[(sk, x)]
            per = {}
            for var in VARS:
                d = delta(i, j, var)
                per[var] = dict(Δ={k: round(v, 2) for k, v in d.items()}, 判定=verdict(d),
                                X=row(i, var), NASDAQ100=row(j, var))
            vs = {var: per[var]['判定'] for var in VARS}
            ent['判定'][x] = dict(感度ごと=per, まとめ=summarize(vs))
            verdicts[f'{sk}:{x}'] = dict(席=sd['ja'], X=x, 主=vs['main'], 感度=vs, まとめ=summarize(vs))
        slots_out[sk] = ent

    # ── 相関（A1・A2 の窓・毎月の対数リターン） ──
    def corr(S):
        s = np.sqrt(np.diag(S))
        return S / np.outer(s, s)
    c1, c2 = corr(ctx['S1']), corr(ctx['S2'])
    corr_out = {f'{a}': {'A1(2000-09〜)': {b: round(float(c1[C.index(a), C.index(b)]), 2) for b in PEERS if b != a},
                         'A2(2011-10〜)': {b: round(float(c2[C.index(a), C.index(b)]), 2) for b in PEERS if b != a}} for a in ('ITA', 'XLK')}

    # ── 中身の重なり（out/etf_profiles.json の掲載＝ほぼ全量） ──
    prof = json.load(open(os.path.join(BASE, 'out', 'etf_profiles.json'))).get('etfs') or {}
    H = {t: {h[0].upper(): float(h[1]) for h in (prof.get(t) or {}).get('h') or []} for t in ('ITA', 'XLK', 'QQQ', 'SMH')}
    hold = {}
    for t in ('ITA', 'XLK'):
        h = H[t]; tot = sum(h.values())
        inq = sum(w for k, w in h.items() if k in H['QQQ'])
        inqs = sum(w for k, w in h.items() if k in H['QQQ'] or k in H['SMH'])
        top = sorted(h.items(), key=lambda kv: -kv[1])
        hold[t] = {'本数': len(h), '掲載の合計(%)': round(100 * tot, 1), 'asof': (prof.get(t) or {}).get('asof'),
                   '実質の銘柄数(1/HHI)': (prof.get(t) or {}).get('eff_n'),
                   '上位5': [[k, round(100 * w, 2)] for k, w in top[:5]],
                   '上位2の合計(%)': round(100 * sum(w for _, w in top[:2]), 1),
                   'NASDAQ100にも入っている会社の比重(%)': round(100 * inq / tot, 1),
                   'NASDAQ100かSMHに入っている会社の比重(%)': round(100 * inqs / tot, 1),
                   '個別株の候補と重なる会社(%)': {k: round(100 * h[k], 2) for k in CASTLE if k in h}}

    # ── 年ごとのリターン・最大下落の時期・直近の年率（データの器の値＝費用前） ──
    k1 = CB.R.months(*CB.R.A1)
    years = {}
    for c in SHOW:
        ch = chains[c]
        years[c] = {}
        for y in YEARS:
            ms = [m for m in k1 if m // 100 == y]
            if ms:
                years[c][str(y) + ('（1〜9月）' if y == 2026 else '')] = round(100 * (float(np.prod([1 + ch[m] for m in ms])) - 1), 1)
    dd = {}
    for c in SHOW:
        lv, peak, pk_m, best = 1.0, 1.0, k1[0], (0.0, None, None)
        path = []
        for m in k1:
            lv *= 1 + chains[c][m]
            path.append((m, lv))
            if lv > peak:
                peak, pk_m = lv, m
            ddv = lv / peak - 1
            if ddv < best[0]:
                best = (ddv, pk_m, m)
        rec = None
        if best[1] is not None:
            pk_lv = dict(path)[best[1]]
            for m, v in path:
                if m > best[2] and v >= pk_lv:
                    rec = m
                    break
        dd[c] = dict(最大下落=round(100 * best[0], 1), 山=best[1], 底=best[2], 戻った月=rec)
    trail = {}
    for c in SHOW:
        trail[c] = {}
        for n_m in (12, 36, 60, 120):
            ms = k1[-n_m:]
            g = float(np.prod([1 + chains[c][m] for m in ms]))
            trail[c][f'直近{n_m // 12}年(%/年)'] = round(100 * (g ** (12 / n_m) - 1), 1)

    one = {c: dict(世界ごと={w: round(100 * rows[c][w], 2) for w in ('A1', 'A2', 'B', 'C')},
                   ぶれ=round(100 * rows[c]['vol_A1'], 1), 最大下落=round(100 * rows[c]['maxdd_A1'], 1)) for c in SHOW}

    doc = dict(generated=datetime.date.today().isoformat(), tool='night/etf_ita_xlk.py',
               question='ITA と XLK を入れる価値はある？（同じ重みを NASDAQ100 に回した形との差）',
               rule=dict(価値あり='Δ平均≥+0.10 かつ Δ最悪≥+0.10 かつ Δぶれ≤+0.5 かつ Δ確率≥−1.0',
                         価値なし='Δ平均≤0 かつ Δ最悪≤0', 差が小さい='|Δ平均|<0.10 かつ |Δ最悪|<0.10 かつ |Δぶれ|<1.0',
                         まとめ='主が価値ありで5本中4本以上が価値あり→堅い価値あり／主が価値なしか差が小さいで4本以上が同じ側→堅い価値なし〜小さい／他は前提しだい',
                         感度=VARS_JA),
               verdicts=verdicts, slots=slots_out, single=one, corr=corr_out, holdings=hold,
               years=years, drawdowns=dd, trailing=trail,
               notes=['ITA の A1 は 2006-05 より前を FSDAX（Fidelity の航空・防衛の能動の投信）でつないでいる',
                      '年ごとのリターン・最大下落の時期・直近の年率はデータの器の値（費用前）。4つの世界の数字は費用と外国税を引いた後',
                      '席Aの主は etf_forward_combo の other15 の表で既に見ていた（盲検ではない）'],
               **{'⚠': ['4つの世界は仮定で重みは同じ。確率はこの仮定の上の数字（毎月を独立な正規分布と置いた）',
                        'ぶれと相関は 2000-2026 と同じと置いた（K2 だけ 2011-2026）',
                        '個別株の15%は物差しの外。判定・配分には使わない（材料）']})
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print(f'→ {OUT}（{time.time() - t0:.0f}秒）')

    for sk, ent in slots_out.items():
        print(f"■ {sk} {ent['ja']}  上位3 平均{ent['上位3']['平均']} 最悪{ent['上位3']['最悪']} 確率{ent['上位3']['確率']}")
        for x in ['QQQM'] + SLOTS[sk]['targets'] + [c for c in ('XLE', 'VBR', 'VTV', 'XLV', 'GLDM', 'VOO') if c not in SLOTS[sk]['targets']]:
            t = ent['table'][x]; r_ = ent['順位'][x]
            print(f"  {x:<5} 平均{t['平均']:6.2f} 最悪{t['最悪']:5.2f} 確率{t['確率']:5.1f} 5%未満{t['五未満']:5.1f} ぶれ{t['ぶれ']:5.1f} 下落{t['最大下落']:6.1f} 過去20年{t['過去20年で15%以上']:5.1f} 15年{t['過去15年で15%以上']:5.1f} 順位{r_}")
        for x, v in ent['判定'].items():
            print(f"  ▶ {x}: まとめ {v['まとめ']}")
            for var in VARS:
                p = v['感度ごと'][var]
                print(f"     {var:<4} {p['判定']:<6} Δ {p['Δ']}")
    print('相関', json.dumps(corr_out, ensure_ascii=False))
    print('中身', json.dumps(hold, ensure_ascii=False))
    print('年', json.dumps(years, ensure_ascii=False))
    print('最大下落', json.dumps(dd, ensure_ascii=False))
    print('直近', json.dumps(trail, ensure_ascii=False))


if __name__ == '__main__':
    main()
