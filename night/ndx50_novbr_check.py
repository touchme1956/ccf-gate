#!/usr/bin/env python3
"""night/ndx50_novbr_check.py — NASDAQ100 50% を固定し VBR を入れない形の中で「最もいい」形を選ぶ（2026-11-09・参考・配分は変えない）

ユーザー「NASDAQ100を50％にした案でいきたい。」→「VBRをなくした形でもっともいいのは？」
門・採点・配分（portfolio.json）・注文書には触れない。
★形・物差し・選び方はこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする
  （見たあとの数字: 同じ日の会話で NASDAQ100 50 の形を4つ測った＝SMH25/FBT15/ITA10・SMH30/FBT10/ITA10・
   SMH20/FBT10/ITA10/VBR10・SMH20/ITA20/XLV10 と、SMH20/FBT15/ITA10/VBR5・SMH25/FBT10/ITA10/VBR5。
   このうち VBR を含まないのは SMH25/FBT15/ITA10・SMH30/FBT10/ITA10・SMH20/ITA20/XLV10 の3つ）。

形: NASDAQ100（物差しでは QQQM）50 を固定・残り50を SMH・FBT・ITA・XLV に5%刻みで配る全286通り（0%も可・VBR は0）。
    今（portfolio.json と照合）を並べて比べる。
物差し（ndx40_form_check・five_mix_ndx と同じ関数・同じ値）:
  元の物差し（best15_check.Fast: P15π・平均・5%未満・最悪の世界・最大下落・ぶれ・過去の転がる20年で15%以上）／
  業種の基礎率の物差し（best15r_check.FastBR: 平均・P15・P5・感度6本）／100年の代用（best15_check.Cent・30年の積立の比 中央・最悪）／
  実績（2000-09〜2026-09 の転がる20年の毎月の積立: 年15%以上の割合・年率の中央・最悪）／
  上位の形だけ: 道の束の年率の分位（upside_check.upside: 真ん中・20%以上）と中身の集中（lookthrough）
選び方（結果を見る前に固定）:
  今の配分（11-02）を決めた five_mix_ndx と同じ4つの目標＝ g1 元の P15π・g2 業種の基礎率の平均（主）・g3 100年の代用の30年の中央・
  g4 実績の20年積立の年率の中央 を、286通りの中の最良を0・最悪を1とする取り逃がしに直し、その最大が最小の形が答え
  （小数3桁で同じなら 取り逃がしの合計が小さい → g4 が高い → g1 が高い → 名前 の順）。物差しが測れない形（ok でない）は外す。
  守りの線（今と比べる）は置かない——NASDAQ100 を50にすると今（NASDAQ100 40・VBR 15）より守りが薄い形しか無いため（会話で見た事実）。
  参考（判定に使わない）: 業種の基礎率の感度6本それぞれで g2 を替えたときの答え・SMH の比ごとの最良・P15π だけで選んだ最良。
⚠ 限界: 実績は 2000-09〜の一つの時代・4つの目標を等しく扱う割り方は five_mix_ndx の決まりの写し・物差しは税と NISA の枠を含まない・
  未来の世界も予想・分散の上乗せは仮定・FBT の上振れの多くは値動きの大きさ（best15_fbt_why）・5%の差は雑音に近い
使い方: python3 night/ndx50_novbr_check.py → out/ndx50_novbr_check.json（約1分）
"""
import contextlib, io, itertools, json, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'ndx50_novbr_check.json')

import best15_check as B   # noqa: E402
import best15r_check as BR  # noqa: E402
from five_mix_ndx_check import realized  # noqa: E402

NDX = 50
REST = ['SMH', 'FBT', 'ITA', 'XLV']
STEP = 5
SDEC = 3
NOW = {'QQQM': 40, 'SMH': 20, 'ITA': 15, 'XLV': 10, 'VBR': 15}
JA = {'QQQM': 'NASDAQ100', 'SMH': 'SMH', 'FBT': 'FBT', 'ITA': 'ITA', 'XLV': 'XLV', 'VBR': 'VBR'}


def log(*a):
    print('[ndx50_novbr]', *a, flush=True)


def check_now():
    t = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    w = {('QQQM' if k == 'IFREE-NDX' else k): v for k, v in t['ami_weights'].items() if v}
    if w != NOW or float(t.get('shiro_castle_pct') or 0) != 0:
        raise SystemExit(f'今の形が正本と違う: {w}（NOW を直してから回す）')


def name(f):
    return ' / '.join(f'{JA[c]} {v}' for c, v in f.items() if v)


def forms():
    out = []
    for v in itertools.product(range(0, (100 - NDX) // STEP + 1), repeat=len(REST)):
        if sum(v) * STEP != 100 - NDX:
            continue
        f = {'QQQM': NDX}
        f.update({c: x * STEP for c, x in zip(REST, v)})
        out.append(f)
    return out


def main():
    t0 = time.time()
    check_now()
    import unx_assets as U
    import upside_check as UC
    import etf_forward_combo as CB
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    P = BR.POOL
    for c in ['QQQM', 'VBR'] + REST:
        if c not in P or c not in rows:
            raise SystemExit(f'物差しに無い本: {c}')
    B.century_extend(U)
    fast, cent = B.Fast(U, rows, chains, P), B.Cent(U, P)
    fbr = BR.FastBR(fast)
    st = BR.industry_state()
    vec, _ = BR.industry_vectors(U, rows)
    adj = {nm: BR.adj_vector(vec, st, rt, P)[0] for nm, rt in BR.RATES.items()}
    a0 = adj['主（20年の値）']
    _, sim = U.tables()

    F = forms()
    assert len(F) == 286, len(F)
    allf = [dict(NOW)] + F
    W = np.array([[f.get(c, 0) for c in P] for f in allf], dtype=np.float64)
    e, b, c, rz = fast.eval(W), fbr.eval(W, a0), cent.eval(W), realized(W, fast)
    # 業種の基礎率の感度6本（ndx40_form_check と同じ呼び方）
    var = {'主': lambda: fbr.eval(W, a0), '10年の値': lambda: fbr.eval(W, adj['10年の値']),
           '1位の業種を強く': lambda: fbr.eval(W, adj['1位の業種を強く（10年の値・Chips −4.0）']),
           '主の半分': lambda: fbr.eval(W, adj['主の半分']), '分散の上乗せなし': lambda: fbr.eval(W, a0, nobonus=True),
           '共分散をA2の窓から': lambda: fbr.eval(W, a0, cov2=True)}
    assert list(var) == list(BR.VARS), (list(var), BR.VARS)
    g2v = {k: v()['mean_pi'] for k, v in var.items()}

    ok = e['ok'] & b['ok'] & c['ok']
    idx = [i for i in range(1, len(allf)) if ok[i]]
    G = {'g1': e['P15'], 'g2': b['mean_pi'], 'g3': c['c30med'], 'g4': rz['med']}

    def pick(Gs, ii):
        best = {g: float(np.max(Gs[g][ii])) for g in Gs}
        worst = {g: float(np.min(Gs[g][ii])) for g in Gs}
        reg = {g: (best[g] - Gs[g]) / (best[g] - worst[g]) for g in Gs}
        R = np.maximum.reduce([reg[g] for g in Gs])
        Rs = sum(reg[g] for g in Gs)
        order = sorted(ii, key=lambda i: (round(float(R[i]), SDEC), round(float(Rs[i]), 9), -float(Gs['g4'][i]), -float(Gs['g1'][i]), name(allf[i])))
        return order, reg, R, Rs

    order, reg, R, Rs = pick(G, idx)
    ans = order[0]

    def row(i, deep=False):
        f = allf[i]
        out = dict(形=name(f), 取り逃がし={g: round(float(reg[g][i]), 3) for g in reg} if i else None,
                   取り逃がしの最大=round(float(R[i]), 3) if i else None,
                   元=dict(P15π=round(100 * float(e['P15'][i]), 1), 平均=round(100 * float(e['mean_pi'][i]), 2),
                          P5π=round(100 * float(e['P5'][i]), 1), 最悪の世界=round(100 * float(e['worst'][i]), 2),
                          最大下落=round(100 * float(e['mdd'][i]), 1), ぶれ=round(100 * float(e['vol'][i]), 1)),
                   基礎率=dict(平均=round(100 * float(b['mean_pi'][i]), 2), P15=round(100 * float(b['P15'][i]), 1), P5=round(100 * float(b['P5'][i]), 1),
                            感度6本の今との差={k: round(100 * float(g2v[k][i] - g2v[k][0]), 2) for k in g2v}),
                   百年=dict(三十年の中央=round(float(c['c30med'][i]), 3), 三十年の最悪=round(float(c['c30min'][i]), 3)),
                   実績=dict(年15以上の割合=round(100 * float(rz['share'][i]), 1), 年率の中央=round(100 * float(rz['med'][i]), 2),
                           年率の最悪=round(100 * float(rz['worst'][i]), 2)))
        if deep:
            Wn = W[i] / W[i].sum()
            geo, _, _ = CB.path_stats((Wn @ fast.G1)[None, :], fast.T1)
            wadj = float(Wn @ fast.adj)
            a2 = float(np.expm1(np.log1p(Wn @ fast.G2).sum() * 12 / fast.T2))
            q = float(Wn @ fast.S1 @ Wn)
            bonus = 0.5 * (float(Wn @ fast.s1) - q)
            wv = {'A1': float(geo[0]) + wadj, 'A2': a2 + wadj, 'B': float(np.expm1(Wn @ fast.lB + bonus)),
                  'C': float(np.expm1(Wn @ fast.lC + bonus)), 'D': float(np.expm1(Wn @ fast.lD + bonus))}
            mchk = sum(fast.pi[k] * wv[k] for k in wv) / sum(fast.pi.values())
            assert abs(mchk - float(e['mean_pi'][i])) < 1e-9, (mchk, e['mean_pi'][i])
            qd, pr = UC.upside(sim, {'worlds': wv, 'sig': q ** 0.5}, fast.pi)
            out['道の束'] = dict(真ん中=qd['50%点'], 上位10=qd['90%点'], 下位10=qd['10%点'], P20=pr['P20（道の束）'], P20_A2を外す=pr['P20（A2を外す）'])
            out['中身の集中'] = B.lookthrough({k: v for k, v in f.items() if v})
        return out

    # 参考（判定に使わない）
    stab = {}
    for k in g2v:
        Gk = dict(G); Gk['g2'] = g2v[k]
        o, _, _, _ = pick(Gk, idx)
        stab[k] = name(allf[o[0]])
    by_smh = {}
    for s in range(0, 51, 5):
        ii = [i for i in idx if allf[i]['SMH'] == s]
        if ii:
            by_smh[f'SMH {s}'] = row(min(ii, key=lambda i: (round(float(R[i]), SDEC), round(float(Rs[i]), 9), name(allf[i]))))['形']
    p15_best = max(idx, key=lambda i: (float(e['P15'][i]), name(allf[i])))
    seen = {'NASDAQ100 50 / SMH 25 / FBT 15 / ITA 10', 'NASDAQ100 50 / SMH 30 / FBT 10 / ITA 10', 'NASDAQ100 50 / SMH 20 / ITA 20 / XLV 10'}
    out = dict(generated=time.strftime('%Y-%m-%d'), tool='night/ndx50_novbr_check.py', kind='参考・配分は変えない',
               question='NASDAQ100 50% を固定し VBR を入れない形で最もいい形は（ユーザー 2026-11-09）',
               形の数=len(F), 測れた形の数=len(idx),
               答え=row(ans, deep=True), 今=row(0, deep=True),
               上位10=[row(i) for i in order[:10]],
               参考_会話で先に見た3つ={allf[i] and name(allf[i]): row(i, deep=True) for i in idx if name(allf[i]) in seen},
               参考_P15πだけで選んだ最良=row(p15_best, deep=True),
               参考_基礎率の感度6本ごとの答え=stab,
               参考_SMHの比ごとの最良=by_smh,
               secs=round(time.time() - t0, 1))
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    log('答え', out['答え']['形'], '取り逃がしの最大', out['答え']['取り逃がしの最大'])
    for r_ in out['上位10']:
        log('  ', r_['形'], r_['取り逃がしの最大'], r_['元']['P15π'], r_['基礎率']['平均'], r_['百年']['三十年の中央'], r_['実績']['年率の中央'])
    log('感度ごとの答え', stab)
    log('SMH の比ごと', by_smh)
    log('P15π だけ', out['参考_P15πだけで選んだ最良']['形'])
    log('→', OUT, f"{out['secs']}秒")


if __name__ == '__main__':
    main()
