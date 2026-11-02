#!/usr/bin/env python3
"""night/five_mix_check.py — NASDAQ100・SMH・ITA・XLV・VBR の5本で組む（five_mix・2026-11-01・参考・配分は変えない）

ユーザー「難しいね。NASDAQSMHITAXLVVBRで組んで」（直前の流れ: 業種は勝ち続けない〔best15r〕→ NASDAQ100 と小型バリューは
主役が入れ替わっても補い合う〔ndx_sv_check〕→ 型の2〜3本の組で堅いのは NASDAQ100＋小型バリュー〔style_combo_check〕）。
門・採点・配分（portfolio.json）・注文書には触れない。
★形・物差し・条件・選び方はこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする。
  回す前に見ていた数字: 今・NASDAQ100 50/VBR 50・NASDAQ100 50/VBR 20/ITA 20/XLV 10 ほか ndx_sv_check の6つの形
  （選び方はそれを知った上で決めた＝その形が答えになるかは、この頭の決まりだけで決まる）

形: NASDAQ100（iFreeNEXT＝物差しでは QQQM）・SMH・ITA・XLV・VBR の5本すべて5%以上・1本50%まで（今の最大の1本）・5%刻み・合計100%
   （個別株0%＝今の正本のまま）＝3,246通り
今: 正本 portfolio.json の ETF 側（QQQM50/SMH20/ITA20/XLV10・個別株0%・読み込んで確かめる＝best15_check.check_now）
物差し（どれもこれまでと同じ道具をそのまま使う）:
  元の物差し＝unx_assets.measure の USD・崩れあり（2000-09〜2026-09・5つの世界 A1・A2・B・C・D・π は bestpf_calibration）を
             行列で写した best15_check.Fast
  基礎率の物差し＝best15r_check.FastBR（未来の3つの世界 B・C・D だけ・業種の基礎率の補正〔主＝20年の値〕）
  100年の代用＝best15_check.Cent（30年の毎月の積立 起点1965〜1995・市場との比・VBR の写しは French の SMALL HiBM＝century_extend）
目標（3つ）:
  g1 元の物差しの P15π（20年の毎月の積立の内部収益率が年15%以上になる確率・直近の流れも含む＝15%を狙う力）
  g2 基礎率の物差しの π加重の平均の年率（業種は勝ち続けない前提の期待値）
  g3 100年の代用の30年の積立の比の中央（主役が入れ替わった100年）
守りの条件（どれも今を下回らない）:
  ① 基礎率の物差しの 5%未満（P5π）≤ 今 ② 最大下落（2000-09〜2026-09・ドル）≥ 今（同じか浅い）
  ③ 100年の代用の30年の積立の比の最悪 ≥ 今
  ④ 勝ち業種（直近10年の年率の上位5業種 ∪ 比重が過去最大の業種＝best15r_check.industry_state と同じ）の中身の比重の合計 ≤ 今
     （半導体・テックへの寄せを今より強めない）
選び方＝取り逃がしの最大を最小に（minimax regret）: 守りの条件を通った形の中で、目標ごとに
  取り逃がし＝(その中の最良 − その形) ÷ (その中の最良 − その中の最悪)（0〜1）。3つの取り逃がしの最大を最小にする形。
  小数3桁に丸めて同じなら 取り逃がしの合計が小さい → g1 が大きい → g2 が大きい → 最大下落が浅い → 名前の順
最終の確かめ（選び方の順に上位30・最初に通った形を答えにする）:
  F1 基礎率の感度6本（主・10年の値・1位の業種を強く・主の半分・分散の上乗せなし・共分散をA2の窓から）すべてで
     平均 ≥ 今 ∧ 5%未満 ≤ 今（同じ感度で測った今と比べる）
  F2 円で見た最大下落（2000-09〜）≥ 今
  F3 小型バリューの上乗せが消えたら（ndx_sv_check の S2: B の世界の VBR から100年の上乗せ B_X×0.5 を引き、C・D の VBR を VOO と同じに）
     でも基礎率の物差しの 5%未満 ≤ 今
  通る形が無ければ「5本で守りを今より悪くしない形は無い」
併せて出す（判定に使わない）: VBR の比ごと（5〜50%）・SMH の比ごとの選び方の最良（同じ最良・最悪で割った取り逃がし・F1〜F3 の合否）／
  目標ごとの最良の形／参考の形（今・5本を等分・NASDAQ100 50/VBR 50・NASDAQ100 50/VBR 20/ITA 20/XLV 10）／答えと参考の詳しい物差し
  （元の物差しと感度5本〔ndx_swap_check.variants〕の今との差・基礎率の物差しと感度6本の今との差・小型バリューの上乗せが消えたら S1・S2・
  100年の代用の20年と30年・転がる10年・20年〔100年の代用の写し・1966-01〜・一括〕で市場に勝った割合・円の枠・中身の集中〔lookthrough〕・
  勝ち業種の中身の比重・B の世界の記録の割り引きとの重なり〔best15r の追記と同じ〕）
⚠ 限界: 3つの目標の割り方（条件を通った5本の形の中の最良と最悪の幅で割る）は私が決めた＝形の幅が変われば答えも動く・
  元の物差しの歴史の世界は2000年以降のテックの時代・基礎率は業種の中央値でばらつきが大きい・100年の写しは後から勝ちが分かった業種
  （医薬品・防衛）を含み、VBR の写しは紙の上の小型バリュー（費用なし）・小型バリューの上乗せは100年の平均で2007年以降は弱い（ndx_sv_check）・
  未来の世界も予想・分散の上乗せは仮定・税は入らない・5%以上・50%まで・5%刻みは私が決めた
使い方: python3 night/five_mix_check.py → out/five_mix_check.json
"""
import contextlib, io, itertools, json, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'five_mix_check.json')

import best15_check as B   # noqa: E402
import best15r_check as BR  # noqa: E402

FIVE = ['QQQM', 'SMH', 'ITA', 'XLV', 'VBR']
JA = {'QQQM': 'NASDAQ100', 'SMH': 'SMH', 'ITA': 'ITA', 'XLV': 'XLV', 'VBR': 'VBR'}
UNITS, LO, HI, STEP = 20, 1, 10, 5            # 5%刻み・5%以上・50%まで
SDEC, NFIN, EPS = 3, 30, 1e-12
GOALS = ['g1', 'g2', 'g3']
GOAL_JA = {'g1': '元の物差しの P15π（15%を狙う力）', 'g2': '基礎率の物差しの平均（業種は勝ち続けない前提の期待値）',
           'g3': '100年の代用の30年の中央（主役が入れ替わった100年）'}
REFS = {'5本を等分': {c: 20 for c in FIVE},
        'NASDAQ100 50/VBR 50': {'QQQM': 50, 'VBR': 50},
        'NASDAQ100 50/VBR 20/ITA 20/XLV 10（今の SMH を VBR へ）': {'QQQM': 50, 'VBR': 20, 'ITA': 20, 'XLV': 10}}


def log(*a):
    print('[five_mix]', *a, flush=True)


def forms5():
    out = [v for v in itertools.product(range(LO, HI + 1), repeat=len(FIVE)) if sum(v) == UNITS]
    return np.array(out, dtype=np.int8)


def name5(f):
    return ' / '.join(f'{JA[c]} {int(f.get(c, 0))}' for c in FIVE if f.get(c, 0) > 0)


def r(x, d=2, k=100):
    return None if x is None or not np.isfinite(x) else round(k * float(x), d)


def main():
    t0 = time.time()
    B.check_now()
    import unx_assets as U
    import upside_check as UC
    import bestpf_check as BC
    import etf_forward_combo as CB
    import ndx_swap_check as N
    from ndx_sv_check import Roll, stats, mrange
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    P = BR.POOL
    miss = [c for c in FIVE if c not in P or c not in rows]
    if miss:
        raise SystemExit(f'物差しに無い本: {miss}')
    C = B.century_extend(U)
    fast, cent = B.Fast(U, rows, chains, P), B.Cent(U, P)
    fbr = BR.FastBR(fast)
    st = BR.industry_state()
    vec, vchk = BR.industry_vectors(U, rows)
    win = list(dict.fromkeys(st['top5'] + st['rec']))
    IND = np.array([[(st['mkt'].get(k, 0.0) if c == 'VOO' else vec.get(c, {}).get(k, 0.0)) for k in win] for c in P])
    adj = {nm: BR.adj_vector(vec, st, rt, P)[0] for nm, rt in BR.RATES.items()}
    a0 = adj['主（20年の値）']
    piB = float(fbr.pi['B'])

    # ── 形 ──
    F5 = forms5()
    ix = [P.index(c) for c in FIVE]
    A = np.zeros((len(F5), len(P)), dtype=np.float64)
    A[:, ix] = F5
    names = [name5({c: int(v) * STEP for c, v in zip(FIVE, row)}) for row in F5]
    W0 = np.array([[B.NOW.get(c, 0) for c in P]], dtype=np.float64)
    log('形', len(A))

    # ── 自己検問: 速い評価と標準の物差しの一致（この5本の形で）──
    rng = np.random.default_rng(5)
    pick = sorted(rng.choice(len(A), size=12, replace=False).tolist())
    fs = {names[i]: {c: int(F5[i][j]) * STEP for j, c in enumerate(FIVE)} for i in pick}
    with contextlib.redirect_stdout(io.StringIO()):
        tab = U.measure(fs, rows, chains, mega=U.mega_map(rows, sorted(set(FIVE) | {'VOO'})),
                        windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
    Wp = A[pick]
    ef, eb0, ec = fast.eval(Wp), fbr.eval(Wp, np.zeros(len(P))), cent.eval(Wp)
    dmax = {}
    for j, nm in enumerate(fs):
        raw = tab[nm]['_raw']
        for k in ('P15', 'P5', 'worst', 'mean_pi', 'mdd', 'vol', 'sig'):
            dmax[k] = max(dmax.get(k, 0.0), abs(float(ef[k][j]) - float(raw[k])))
        for k in ('B', 'C', 'D'):
            dmax['基礎率の物差し（補正0）の世界 ' + k] = max(dmax.get('基礎率の物差し（補正0）の世界 ' + k, 0.0), abs(float(eb0[k][j]) - raw['worlds'][k]))
        cm = U.century_monthly(fs[nm])
        c30 = cm['30年の積立（起点1965〜1995）']
        dmax['c30med'] = max(dmax.get('c30med', 0.0), abs(float(ec['c30med'][j]) - c30['_med']))
        dmax['c30min'] = max(dmax.get('c30min', 0.0), abs(float(ec['c30min'][j]) - min(c30['_v'].values())))
    sc = dict(形=len(fs), 最大の差={k: float(v) for k, v in dmax.items()},
              中身の業種が_rows_と一致={c: bool(vchk[c]) for c in FIVE if c in vchk})
    sc['一致'] = bool(all(v < 1e-9 for v in dmax.values()) and all(sc['中身の業種が_rows_と一致'].values()))
    log('自己検問', json.dumps(sc, ensure_ascii=False))
    if not sc['一致']:
        raise SystemExit('自己検問が通らない')

    # ── 全部の形を測る ──
    e, b, c = fast.eval(A), fbr.eval(A, a0), cent.eval(A)
    e0, b0, c0 = fast.eval(W0), fbr.eval(W0, a0), cent.eval(W0)
    An = A / A.sum(axis=1, keepdims=True)
    winsum = (An @ IND).sum(axis=1)
    win0 = float(((W0 / W0.sum()) @ IND).sum())
    now = dict(g1=float(e0['P15'][0]), g2=float(b0['mean_pi'][0]), g3=float(c0['c30med'][0]), P5b=float(b0['P5'][0]),
               mdd=float(e0['mdd'][0]), c30min=float(c0['c30min'][0]), win=win0)
    G = dict(g1=e['P15'], g2=b['mean_pi'], g3=c['c30med'])
    okall = e['ok'] & b['ok'] & c['ok']
    with np.errstate(invalid='ignore'):
        gate = {'①基礎率の5%未満': b['P5'] <= now['P5b'] + EPS, '②最大下落': e['mdd'] >= now['mdd'] - EPS,
                '③100年の最悪': c['c30min'] >= now['c30min'] - EPS, '④勝ち業種の中身の比重の合計': winsum <= now['win'] + 1e-9}
    feas = okall.copy()
    for v in gate.values():
        feas &= v
    cnt = {k: int((v & okall).sum()) for k, v in gate.items()}
    log('今', {k: round(v, 4) for k, v in now.items()}, '測れた形', int(okall.sum()), '条件ごと', cnt, '全部通った', int(feas.sum()))
    out = dict(generated=time.strftime('%Y-%m-%d'), tool='night/five_mix_check.py', kind='参考（配分は変えない・形と選び方は道具の頭に固定）',
               question='NASDAQ100・SMH・ITA・XLV・VBR の5本で組む', selfcheck=sc, 形の数=len(A), 測れた形=int(okall.sum()),
               守りの条件ごとに通った形=cnt, 守りの条件を全部通った形=int(feas.sum()),
               今=dict(形=dict(B.NOW), **{GOAL_JA[g]: (round(100 * now[g], 2) if g != 'g3' else round(now[g], 3)) for g in GOALS},
                      基礎率の5パーセント未満=round(100 * now['P5b'], 2), 最大下落=round(100 * now['mdd'], 1),
                      百年の最悪=round(now['c30min'], 3), 勝ち業種の中身の比重の合計=round(100 * now['win'], 1)),
               勝ち業種=win)
    if not feas.any():
        out['答え'] = None
        out['結論'] = '5本で守りを今より悪くしない形は無い'
        json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
        log(out['結論'])
        return
    ii = np.where(feas)[0]
    best = {g: float(np.max(G[g][ii])) for g in GOALS}
    worst = {g: float(np.min(G[g][ii])) for g in GOALS}
    reg = {g: (best[g] - G[g]) / (best[g] - worst[g]) if best[g] - worst[g] > EPS else np.zeros(len(A)) for g in GOALS}
    R = np.maximum.reduce([reg[g] for g in GOALS])
    Rs = sum(reg[g] for g in GOALS)

    def order(idx):
        return sorted(list(idx), key=lambda i: (round(float(R[i]), SDEC), round(float(Rs[i]), 9), -float(G['g1'][i]),
                                                -float(G['g2'][i]), -float(e['mdd'][i]), names[i]))
    top = order(ii)[:NFIN]

    def brief(i):
        return dict(名前=names[i], 形={c: int(F5[i][j]) * STEP for j, c in enumerate(FIVE)},
                    取り逃がしの最大=round(float(R[i]), 4), 取り逃がし={g: round(float(reg[g][i]), 3) for g in GOALS},
                    元のP15π=r(e['P15'][i]), 元の平均=r(e['mean_pi'][i]), 元の5パーセント未満=r(e['P5'][i]), 元の最悪の世界=r(e['worst'][i]),
                    過去の転がる20年で15パーセント以上=r(e['past20'][i], 1),
                    基礎率のP15π=r(b['P15'][i]), 基礎率の平均=r(b['mean_pi'][i]), 基礎率の5パーセント未満=r(b['P5'][i]),
                    最大下落=r(e['mdd'][i], 1), ぶれ=r(e['vol'][i], 1), 百年の中央=round(float(c['c30med'][i]), 3),
                    百年の最悪=round(float(c['c30min'][i]), 3), 勝ち業種の中身の比重の合計=r(winsum[i], 1))

    # ── 最終の確かめ（F1〜F3）──
    def ve(Wf, v):
        return {'主': lambda: fbr.eval(Wf, a0), '10年の値': lambda: fbr.eval(Wf, adj['10年の値']),
                '1位の業種を強く': lambda: fbr.eval(Wf, adj['1位の業種を強く（10年の値・Chips −4.0）']),
                '主の半分': lambda: fbr.eval(Wf, adj['主の半分']), '分散の上乗せなし': lambda: fbr.eval(Wf, a0, nobonus=True),
                '共分散をA2の窓から': lambda: fbr.eval(Wf, a0, cov2=True)}[v]()
    ch_jpy, _ = U.jpy_chains(chains)
    Gj = np.array([[ch_jpy[x][m] for m in U.R.months(*BC.WINDOWS[UC.W_CRASH])] for x in P])
    _, _, mdd_j0 = CB.path_stats((W0 / W0.sum()) @ Gj, Gj.shape[1])
    iv, ivoo = P.index('VBR'), P.index('VOO')

    def s_variants(Wf):
        gB0, gC0, gD0 = fbr.gB.copy(), fbr.gC.copy(), fbr.gD.copy()
        o = {}
        try:
            fbr.gB[iv] -= 0.5 * float(rows['VBR']['B_X'])
            o['S1 B の世界の小型バリューの上乗せを0'] = fbr.eval(Wf, a0)
            fbr.gC[iv], fbr.gD[iv] = fbr.gC[ivoo], fbr.gD[ivoo]
            o['S2 未来の3つの世界のどれも小型バリューに上乗せなし'] = fbr.eval(Wf, a0)
        finally:
            fbr.gB, fbr.gC, fbr.gD = gB0, gC0, gD0
        return o
    S0 = s_variants(W0)

    def checks(idx):
        Wt = A[idx]
        vres = {v: (ve(Wt, v), ve(W0, v)) for v in BR.VARS}
        _, _, mdd_j = CB.path_stats((Wt / Wt.sum(axis=1, keepdims=True)) @ Gj, Gj.shape[1])
        Ss = s_variants(Wt)
        rows_out = []
        for j, i in enumerate(idx):
            f1 = {v: dict(平均=bool(vres[v][0]['mean_pi'][j] >= vres[v][1]['mean_pi'][0] - EPS),
                          五パーセント未満=bool(vres[v][0]['P5'][j] <= vres[v][1]['P5'][0] + EPS)) for v in BR.VARS}
            ok1 = all(x['平均'] and x['五パーセント未満'] for x in f1.values())
            ok2 = bool(mdd_j[j] >= mdd_j0[0] - EPS)
            k2 = 'S2 未来の3つの世界のどれも小型バリューに上乗せなし'
            ok3 = bool(Ss[k2]['P5'][j] <= S0[k2]['P5'][0] + EPS)
            rows_out.append(dict(**brief(i), F1=ok1, F2円の最大下落=ok2, F3小型バリューの上乗せなしの5パーセント未満=ok3, 合否=bool(ok1 and ok2 and ok3),
                                 感度ごとの今との差={v: dict(平均=r(vres[v][0]['mean_pi'][j] - vres[v][1]['mean_pi'][0], 3),
                                                         五パーセント未満=r(vres[v][0]['P5'][j] - vres[v][1]['P5'][0]),
                                                         P15=r(vres[v][0]['P15'][j] - vres[v][1]['P15'][0])) for v in BR.VARS},
                                 円の最大下落=r(mdd_j[j], 1),
                                 小型バリューの上乗せが消えたら={k: dict(P15π=r(s['P15'][j]), 平均=r(s['mean_pi'][j]), 五パーセント未満=r(s['P5'][j]),
                                                               今との差=dict(P15=r(s['P15'][j] - S0[k]['P15'][0]), 平均=r(s['mean_pi'][j] - S0[k]['mean_pi'][0], 3),
                                                                          五パーセント未満=r(s['P5'][j] - S0[k]['P5'][0])))
                                                    for k, s in Ss.items()}))
        return rows_out
    finals = checks(top)
    ans = next((x for x in finals if x['合否']), None)
    out['最終の確かめ'] = finals
    out['答え'] = ans
    out['今の円の最大下落'] = r(mdd_j0[0], 1)
    out['結論'] = (f'答え {ans["名前"]}' if ans else '上位30の形はどれも最終の確かめを通らない＝5本で守りを今より悪くしない形は無い')
    log(out['結論'])

    # ── 比ごとの最良・目標ごとの最良 ──
    fr = {}
    for x in ('VBR', 'SMH', 'QQQM'):
        j = FIVE.index(x)
        rows_x = []
        for u in range(LO, HI + 1):
            sel = ii[F5[ii, j] == u]
            if not len(sel):
                rows_x.append(dict(比=u * STEP, 守りの条件を通った形=0))
                continue
            bi = order(sel)[0]
            rows_x.append(dict(比=u * STEP, 守りの条件を通った形=int(len(sel)), **checks([bi])[0]))
        fr[JA[x]] = rows_x
    out['比ごとの最良'] = fr
    out['目標ごとの最良'] = {GOAL_JA[g]: brief(int(ii[np.argmax(G[g][ii])])) for g in GOALS}
    out['最良と最悪（守りの条件を通った形の中）'] = {GOAL_JA[g]: dict(最良=(r(best[g]) if g != 'g3' else round(best[g], 3)),
                                                        最悪=(r(worst[g]) if g != 'g3' else round(worst[g], 3)),
                                                        今=(r(now[g]) if g != 'g3' else round(now[g], 3))) for g in GOALS}

    # ── 答えと参考の詳しい物差し ──
    show = {'今': dict(B.NOW)}
    if ans:
        show['答え'] = dict(ans['形'])
    show.update(REFS)
    Ws = np.array([[f.get(x, 0) for x in P] for f in show.values()], dtype=np.float64)
    es, bs, cs = fast.eval(Ws), fbr.eval(Ws, a0), cent.eval(Ws)
    Vs = {v: ve(Ws, v) for v in BR.VARS}
    Ss = s_variants(Ws)
    Wsn = Ws / Ws.sum(axis=1, keepdims=True)
    assets = sorted({a for f in show.values() for a in f} | {'VOO'})
    with contextlib.redirect_stdout(io.StringIO()):
        mega = U.mega_map(rows, assets)
        tab0 = U.measure(show, rows, chains, mega=mega)
        tj = U.measure(show, rows, ch_jpy, mega=mega, windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
        k4, _ = N.chips_adj(rows, assets)
        vt = N.variants(show, rows, chains, k4)[UC.W_CRASH]
    # 100年の代用の写しで転がる窓（一括・1966-01〜）
    Cc = U.century_parts()
    Fm, parts, mkt, endm = Cc['F'], Cc['parts'], Cc['mkt'], Cc['endm']
    allm = sorted(mkt)
    mix = {}
    for nm, f in show.items():
        tw = sum(f.values())
        mix[nm] = Fm.mix([(w / tw, parts[k]) for k, w in f.items() if w > 0], allm)
    ms = [m for m in allm if 196601 <= m <= endm and all(m in s for s in mix.values())]   # どの形にもそろう月だけ（写しの最後の月が市場より早い）
    if ms != mrange(ms[0], ms[-1]):
        raise SystemExit('100年の写しの月に抜けがある（転がる窓が使えない）')
    ser = {'MKT': {m: mkt[m] for m in ms}}
    for nm in show:
        ser[nm] = {m: mix[nm][m] for m in ms}
    Rr = Roll(ser, ms)
    detail = {}
    for j, (nm, f) in enumerate(show.items()):
        o = tab0[UC.W_CRASH][nm]
        cm = U.century_monthly(f)
        roll = {}
        for n, lab in ((120, '10年'), (240, '20年')):
            ex = [Rr.ann(nm, i, n) - Rr.ann('MKT', i, n) for i in range(len(ms) - n + 1)]
            roll[lab] = stats(ex)
        roll['月'] = f'{ms[0]}〜{ms[-1]}'
        detail[nm] = dict(
            形=f, 名前=name5(f),
            元の物差し=dict(P15π=o['P15π'], 平均=o['π加重の平均の年率'], 五パーセント未満=o['P5π（5%未満）'], 最悪の世界=o['最悪の世界'],
                         最大下落=o['最大下落'], ぶれ=o['ぶれ'], 世界=o['世界ごとの年率'],
                         過去の転がる20年で15パーセント以上=o['過去の転がる20年で15%以上'], 積立20年の内部収益率=o['積立20年の内部収益率']),
            元の物差しの感度ごとの今との差={N.VARS_JA[v]: dict(P15=r(vt[nm][v]['P15'] - vt['今'][v]['P15']),
                                                     平均=r(vt[nm][v]['mean_pi'] - vt['今'][v]['mean_pi'], 3),
                                                     五パーセント未満=r(vt[nm][v]['P5'] - vt['今'][v]['P5'])) for v in N.VARS},
            基礎率の物差し=dict(P15π=r(bs['P15'][j]), 平均=r(bs['mean_pi'][j]), 最悪の世界=r(bs['worst'][j]), 五パーセント未満=r(bs['P5'][j]),
                            世界=dict(B=r(bs['B'][j]), C=r(bs['C'][j]), D=r(bs['D'][j]))),
            基礎率の感度ごとの今との差={v: dict(P15=r(Vs[v]['P15'][j] - Vs[v]['P15'][0]), 平均=r(Vs[v]['mean_pi'][j] - Vs[v]['mean_pi'][0], 3),
                                        五パーセント未満=r(Vs[v]['P5'][j] - Vs[v]['P5'][0])) for v in BR.VARS},
            小型バリューの上乗せが消えたら={k: dict(P15π=r(s['P15'][j]), 平均=r(s['mean_pi'][j]), 五パーセント未満=r(s['P5'][j]))
                                for k, s in Ss.items()},
            百年=dict(三十年の中央=round(float(cs['c30med'][j]), 3), 三十年の最悪=round(float(cs['c30min'][j]), 3),
                    詳細=(None if cm is None else U.strip_century(cm)), 転がる窓_一括_1966から=roll),
            円の枠={k: tj[nm][k] for k in ('π加重の平均の年率', 'P15π', 'P5π（5%未満）', '最大下落', '過去の転がる20年で15%以上')},
            勝ち業種の中身の比重={k: r(Wsn[j] @ IND[:, i], 1) for i, k in enumerate(win)},
            勝ち業種の中身の比重の合計=r(float((Wsn[j] @ IND).sum()), 1),
            二重に数えた分_B_rec=round(100 * piB * sum(w / sum(f.values()) * float(rows[x].get('B_rec') or 0.0) for x, w in f.items()), 3),
            中身の集中=B.lookthrough(f))
        log(nm, json.dumps(dict(元=detail[nm]['元の物差し'] | {'世界': None}, 基礎率=detail[nm]['基礎率の物差し'] | {'世界': None},
                                百年=detail[nm]['百年']['三十年の中央']), ensure_ascii=False))
    out['詳しい物差し'] = detail
    out['secs'] = round(time.time() - t0)
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    log('→', OUT, out['secs'], 's')


if __name__ == '__main__':
    main()
