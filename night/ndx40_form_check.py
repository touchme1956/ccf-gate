#!/usr/bin/env python3
"""night/ndx40_form_check.py — 案「NASDAQ100 40 / SMH 25 / ITA 15 / XLV 10 / VBR 10」を今・芯の答えと同じ物差しで測る（2026-11-02・参考・配分は変えない）

ユーザー「NASDAQ100 40 / SMH 25 / ITA 15 / XLV 10 / VBR 10とあなたならどうする？」
案は five_mix_ndx（night/five_mix_ndx_check.py・985a2478）の芯の答え NASDAQ100 30 / SMH 25 / ITA 15 / XLV 10 / VBR 20 から
VBR の10を NASDAQ100 へ移した形（今〔NASDAQ100 50 / SMH 20 / ITA 20 / XLV 10〕からは NASDAQ100 −10・SMH +5・ITA −5・VBR +10）。
門・採点・配分（portfolio.json）・注文書には触れない。
★測るもの・形・選び方はこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする
  （five_mix_ndx の答えと NASDAQ100 の比ごとの最良の数字は見たあと＝芯40の最良 NASDAQ100 40 / SMH 20 / ITA 10 / XLV 5 / VBR 25 の
   取り逃がしの最大 0.424 も知っている。案と案の隣の数字はまだ見ていない）。

形:
  今          NASDAQ100 50 / SMH 20 / ITA 20 / XLV 10（portfolio.json と照合）
  案          NASDAQ100 40 / SMH 25 / ITA 15 / XLV 10 / VBR 10（ユーザー）
  芯の答え    NASDAQ100 30 / SMH 25 / ITA 15 / XLV 10 / VBR 20（five_mix_ndx の答え）
  芯40の最良  NASDAQ100 40 / SMH 20 / ITA 10 / XLV 5 / VBR 25（five_mix_ndx の NASDAQ100 40 の最良）
  今に VBR    NASDAQ100 50 / SMH 20 / ITA 10 / XLV 10 / VBR 10（参考: NASDAQ100 50・SMH 20 を保って ITA の10を VBR へ）
  案の隣      案から1本の5を別の1本へ移した20通り（5本すべて5%以上のまま）
測るもの（five_mix_ndx と同じ関数・同じ値）:
  元の物差し（unx_assets.measure・USD・崩れあり: P15π・平均・5%未満・最悪の世界・最大下落・ぶれ・世界ごと・過去の転がる20年で15%以上・
    感度5本の今との差）／業種の基礎率の物差し（best15r_check.FastBR: P15π・平均・5%未満・感度6本の今との差・小型バリューの上乗せなし S2）／
  100年の代用（30年の積立の比 中央・最悪・本物の NASDAQ100 を 1985-11 からつないだ感度）／
  実績（2000-09〜2026-09 の転がる20年の毎月の積立: 年15%以上の割合・年率の中央・最悪）／円の枠／勝ち業種の中身の比重の合計／
  中身の集中（lookthrough）／守りの条件4つ（five_mix と同じ・今と比べる）と最終の確かめ F1〜F3（five_mix_ndx と同じ）／
  five_mix_ndx の芯の形（782通り・守りの条件を通った679通り）の中での位置＝4つの目標の取り逃がし（同じ最良と最悪で割る）・その最大・順位
  ＋物差しの外の実務（決まった算数・参考・判定に使わない）: 注文書の毎月の円のうち成長投資枠（NASDAQ100 以外の ETF）へ行く割合の定常の目安と、
    2人の成長投資枠（1,200万円×2）が埋まるまでの年数。NASDAQ100 の区分の目標 t のうち自動の積立（iDeCo・こどもNISA＝portfolio.json）で
    埋まらない分 max(0, t×入金−自動)÷(入金−自動) が つみたて投資枠（iFreeNEXT）・残りが成長投資枠。今の保有のずれ（個別株の引き継ぎ・
    NASDAQ100 の区分が目標を超えている）が戻るまでの移り変わりと、既に使った枠は入れない（repo の記録の多くは口座を持たない＝今の保有の
    取得額の合計を全部が成長投資枠だった場合の上限として併記する）
私の答えの選び方（結果を見る前に固定）:
  NASDAQ100 を核にする理由（年1回の入れ替えで業種の交代に付いていく）の弱い場面は「テック自身が主役を降りるとき」で、
  SMH（固定の半導体）はその場面で一緒に負ける側（docs/CLAUDE_ARCHIVE.md の 2026-11-02 の節）。そこで固定の半導体を今（20%）より
  増やさない＝SMH 20 の縛りを1つだけ案に足し、浮いた5の行き先を NASDAQ100・ITA・XLV・VBR の4通りから選ぶ。
  4通りのうち 守りの条件4つ と F1〜F3 を通った形の中で、five_mix_ndx と同じ4つの目標の取り逃がしの最大が最小の形
  （小数3桁で同じなら five_mix_ndx と同じ並べ方）＝私の答え。どれも通らなければ案のまま。
  参考（判定に使わない）: 縛りを足さずに案と案の隣の21通りを同じ決まりで並べた最良。
⚠ 限界: 実績は 2000-09〜の一つの時代・4つの目標を等しく扱う割り方と SMH 20 の縛りは私が決めた・物差しは税と NISA の枠を含まない・
  未来の世界も予想・分散の上乗せは仮定・100年の写しの NASDAQ100 は業種を固定した代わり（入れ替えを数えない）・案の隣の5%の差は雑音に近い
使い方: python3 night/ndx40_form_check.py → out/ndx40_form_check.json（約30秒）
"""
import contextlib, io, json, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'ndx40_form_check.json')
REF = os.path.join(BASE, 'out', 'five_mix_ndx_check.json')

import best15_check as B   # noqa: E402
import best15r_check as BR  # noqa: E402
import best15c_check as BCc  # noqa: E402
from five_mix_check import FIVE, JA, name5, r  # noqa: E402
from five_mix_ndx_check import forms_core, realized, STEP, SDEC, NFIN, EPS, GOALS, GOAL_JA  # noqa: E402

PLAN = {'QQQM': 40, 'SMH': 25, 'ITA': 15, 'XLV': 10, 'VBR': 10}
FORMS = {'今': dict(B.NOW),
         '案': dict(PLAN),
         '芯の答え': {'QQQM': 30, 'SMH': 25, 'ITA': 15, 'XLV': 10, 'VBR': 20},
         '芯40の最良': {'QQQM': 40, 'SMH': 20, 'ITA': 10, 'XLV': 5, 'VBR': 25},
         '今に VBR': {'QQQM': 50, 'SMH': 20, 'ITA': 10, 'XLV': 10, 'VBR': 10}}
MINE_FROM, MINE_TO = 'SMH', ['QQQM', 'ITA', 'XLV', 'VBR']
GROWTH_CAP_PER_PERSON = 12_000_000           # NISA 成長投資枠の生涯の上限（1人）
TSUMITATE_CAP_MONTH_PER_PERSON = 100_000     # つみたて投資枠 年120万円÷12（1人）
REF_ANSWER = 'NASDAQ100 30 / SMH 25 / ITA 15 / XLV 10 / VBR 20'


def log(*a):
    print('[ndx40_form]', *a, flush=True)


def neighbors(f):
    out = {}
    for a in FIVE:
        for b in FIVE:
            if a == b:
                continue
            g = {c: f.get(c, 0) for c in FIVE}
            g[a] -= STEP
            g[b] += STEP
            if min(g.values()) < 5:
                continue
            out[f'{JA[a]}→{JA[b]}'] = {c: v for c, v in g.items() if v > 0}
    return out


def nisa_steady(f, tgt, cost_now):
    D = int(tgt['nisa']['monthly_total_jpy'])
    auto = 0
    for key in ('ideco', 'kodomo_nisa'):
        cfg = tgt.get(key) or {}
        if cfg.get('bucket') != 'IFREE-NDX':
            raise SystemExit(f'{key} の区分が NASDAQ100 ではない: {cfg.get("bucket")}')
        auto += sum(int(m.get('jpy') or 0) for m in cfg.get('members') or [])
    order = D - auto
    holders = len(tgt['nisa']['holders'])
    t = f.get('QQQM', 0) / 100.0
    ndx_order = min(max(0.0, t * D - auto), order)
    if ndx_order > TSUMITATE_CAP_MONTH_PER_PERSON * holders:
        raise SystemExit('つみたて投資枠の月の上限を超える（この算数の前提が崩れる）')
    growth = order - ndx_order
    cap = GROWTH_CAP_PER_PERSON * holders
    yrs = cap / (growth * 12) if growth > 0 else None
    return dict(入金=D, 自動の積立=auto, 注文書=order, 注文書のうちNASDAQ100_つみたて投資枠=round(ndx_order),
                注文書のうち成長投資枠=round(growth), 成長投資枠へ行く割合=round(100 * growth / order, 1),
                二人の成長投資枠が埋まるまでの年数=(round(yrs, 1) if yrs else None),
                今の保有の取得額が全部成長投資枠だった場合に短くなる年数の上限=(round(cost_now / (growth * 12), 1) if growth > 0 else None))


def main():
    t0 = time.time()
    B.check_now()
    import unx_assets as U
    import upside_check as UC
    import bestpf_check as BC
    import etf_forward_combo as CB
    import ndx_swap_check as N
    import bestfund_data as D
    ref = json.load(open(REF))
    tgt = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    st_json = json.load(open(os.path.join(BASE, 'state.json')))
    pfj = st_json['data']['pf:portfolio']
    pfj = json.loads(pfj) if isinstance(pfj, str) else pfj
    cost_now = float(sum(float(p.get('bjpy') or 0) for p in pfj['positions']))
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    P = BR.POOL
    for c in set(FIVE) | {'VOO'}:
        if c not in P or c not in rows:
            raise SystemExit(f'物差しに無い本: {c}')
    C = B.century_extend(U)
    fast, cent = B.Fast(U, rows, chains, P), B.Cent(U, P)
    fbr = BR.FastBR(fast)
    st = BR.industry_state()
    vec, vchk = BR.industry_vectors(U, rows)
    win = list(dict.fromkeys(st['top5'] + st['rec']))
    IND = np.array([[(st['mkt'].get(k, 0.0) if c == 'VOO' else vec.get(c, {}).get(k, 0.0)) for k in win] for c in P])
    adj = {nm: BR.adj_vector(vec, st, rt, P)[0] for nm, rt in BR.RATES.items()}
    a0 = adj['主（20年の値）']

    # 100年の写しの感度（five_mix_ndx と同じ）
    ndx, _, _ = D.build_chain('NDX')
    parts_alt = dict(C['parts'])
    q = dict(C['parts']['QQQM'])
    for m in list(q):
        if m >= 198511:
            if m not in ndx:
                raise SystemExit(f'本物の NASDAQ100 に {m} が無い')
            q[m] = ndx[m]
    parts_alt['QQQM'] = q
    cent_alt = BCc.CentP(U, P, parts_alt)
    cent_chk = BCc.CentP(U, P, dict(C['parts']))

    def W_of(forms):
        return np.array([[f.get(c, 0) for c in P] for f in forms], dtype=np.float64)

    # 自己検問（five_mix_ndx と同じ）
    rng = np.random.default_rng(3)
    Wr = rng.integers(0, 9, size=(40, len(P))).astype(np.float64)
    Wr[Wr.sum(axis=1) == 0, 0] = 1
    d_share = float(np.max(np.abs(realized(Wr, fast)['share'] - fast.eval(Wr)['past20'])))
    with np.errstate(invalid='ignore'):
        d_cent = float(np.nanmax(np.abs(cent.eval(Wr)['c30med'] - cent_chk.eval(Wr)['c30med'])))
    sc = dict(実績の年15パーセント以上の割合が_Fast_の_past20_と一致=d_share, 写しを替えないCentPがCentと一致=d_cent,
              中身の業種が_rows_と一致={c: bool(vchk[c]) for c in FIVE if c in vchk})

    # five_mix_ndx の芯の形と最良・最悪（同じ式で作り直す）
    F5 = forms_core()
    ix = [P.index(c) for c in FIVE]
    A = np.zeros((len(F5), len(P)), dtype=np.float64)
    A[:, ix] = F5
    names = [name5({c: int(v) * STEP for c, v in zip(FIVE, row)}) for row in F5]
    W0 = W_of([B.NOW])
    e, b, c, rz = fast.eval(A), fbr.eval(A, a0), cent.eval(A), realized(A, fast)
    e0, b0, c0, rz0 = fast.eval(W0), fbr.eval(W0, a0), cent.eval(W0), realized(W0, fast)
    winsum = ((A / A.sum(axis=1, keepdims=True)) @ IND).sum(axis=1)
    now = dict(P5b=float(b0['P5'][0]), mdd=float(e0['mdd'][0]), c30min=float(c0['c30min'][0]), win=float(((W0 / W0.sum()) @ IND).sum()))
    G = dict(g1=e['P15'], g2=b['mean_pi'], g3=c['c30med'], g4=rz['med'])
    okall = e['ok'] & b['ok'] & c['ok']

    def gates(e_, b_, c_, win_):
        with np.errstate(invalid='ignore'):
            return {'①基礎率の5%未満': b_['P5'] <= now['P5b'] + EPS, '②最大下落': e_['mdd'] >= now['mdd'] - EPS,
                    '③100年の最悪': c_['c30min'] >= now['c30min'] - EPS, '④勝ち業種の中身の比重の合計': win_ <= now['win'] + 1e-9}
    feas = okall.copy()
    for v in gates(e, b, c, winsum).values():
        feas &= v
    ii = np.where(feas)[0]
    best = {g: float(np.max(G[g][ii])) for g in GOALS}
    worst = {g: float(np.min(G[g][ii])) for g in GOALS}

    def regret_of(vals):
        reg = {g: (best[g] - vals[g]) / (best[g] - worst[g]) for g in GOALS}
        return reg, np.maximum.reduce([reg[g] for g in GOALS]), sum(reg[g] for g in GOALS)
    reg, R, Rs = regret_of(G)

    def key_of(Rm, Rsum, g4, g1, mdd, nm):
        return (round(float(Rm), SDEC), round(float(Rsum), 9), -float(g4), -float(g1), -float(mdd), nm)
    order = sorted(list(ii), key=lambda i: key_of(R[i], Rs[i], G['g4'][i], G['g1'][i], e['mdd'][i], names[i]))

    # 最終の確かめ（five_mix_ndx と同じ F1〜F3）
    def ve(Wf, v):
        return {'主': lambda: fbr.eval(Wf, a0), '10年の値': lambda: fbr.eval(Wf, adj['10年の値']),
                '1位の業種を強く': lambda: fbr.eval(Wf, adj['1位の業種を強く（10年の値・Chips −4.0）']),
                '主の半分': lambda: fbr.eval(Wf, adj['主の半分']), '分散の上乗せなし': lambda: fbr.eval(Wf, a0, nobonus=True),
                '共分散をA2の窓から': lambda: fbr.eval(Wf, a0, cov2=True)}[v]()
    ch_jpy, _ = U.jpy_chains(chains)
    Gj = np.array([[ch_jpy[x][m] for m in U.R.months(*BC.WINDOWS[UC.W_CRASH])] for x in P])
    _, _, mdd_j0 = CB.path_stats((W0 / W0.sum()) @ Gj, Gj.shape[1])
    iv, ivoo = P.index('VBR'), P.index('VOO')

    def s2(Wf):
        gB0, gC0, gD0 = fbr.gB.copy(), fbr.gC.copy(), fbr.gD.copy()
        try:
            fbr.gB[iv] -= 0.5 * float(rows['VBR']['B_X'])
            fbr.gC[iv], fbr.gD[iv] = fbr.gC[ivoo], fbr.gD[ivoo]
            return fbr.eval(Wf, a0)
        finally:
            fbr.gB, fbr.gC, fbr.gD = gB0, gC0, gD0
    S0 = s2(W0)

    def checks_W(Wt):
        vres = {v: (ve(Wt, v), ve(W0, v)) for v in BR.VARS}
        _, _, mdd_j = CB.path_stats((Wt / Wt.sum(axis=1, keepdims=True)) @ Gj, Gj.shape[1])
        Ss = s2(Wt)
        out = []
        for j in range(len(Wt)):
            ok1 = all(vres[v][0]['mean_pi'][j] >= vres[v][1]['mean_pi'][0] - EPS and vres[v][0]['P5'][j] <= vres[v][1]['P5'][0] + EPS for v in BR.VARS)
            ok2 = bool(mdd_j[j] >= mdd_j0[0] - EPS)
            ok3 = bool(Ss['P5'][j] <= S0['P5'][0] + EPS)
            out.append(dict(F1=bool(ok1), F2円の最大下落=ok2, F3小型バリューの上乗せなしの5パーセント未満=ok3, 合否=bool(ok1 and ok2 and ok3),
                            円の最大下落=r(mdd_j[j], 1),
                            基礎率の感度ごとの今との差={v: dict(平均=r(vres[v][0]['mean_pi'][j] - vres[v][1]['mean_pi'][0], 3),
                                                       五パーセント未満=r(vres[v][0]['P5'][j] - vres[v][1]['P5'][0])) for v in BR.VARS},
                            小型バリューの上乗せなし_S2=dict(P15π=r(Ss['P15'][j]), 平均=r(Ss['mean_pi'][j]), 五パーセント未満=r(Ss['P5'][j]),
                                                     今との差_平均=r(Ss['mean_pi'][j] - S0['mean_pi'][0], 3),
                                                     今との差_五パーセント未満=r(Ss['P5'][j] - S0['P5'][0]))))
        return out

    ans_i = None
    for k0 in range(0, len(order), NFIN):
        chunk = order[k0:k0 + NFIN]
        ck = checks_W(A[chunk])
        hit = next((i for i, x in zip(chunk, ck) if x['合否']), None)
        if hit is not None:
            ans_i = hit
            break
    i40 = next(i for i in order if int(F5[i][FIVE.index('QQQM')]) * STEP == 40)
    sc['five_mix_ndx の再現'] = dict(
        守りの条件を通った形=dict(この道具=int(len(ii)), five_mix_ndx=ref['守りの条件を全部通った形']),
        答え=dict(この道具=names[ans_i] if ans_i is not None else None, five_mix_ndx=ref['答え']['名前']),
        答えの取り逃がしの最大=dict(この道具=round(float(R[ans_i]), 4), five_mix_ndx=ref['答え']['取り逃がしの最大']),
        芯40の最良=dict(この道具=names[i40], 取り逃がしの最大=round(float(R[i40]), 4),
                     five_mix_ndx=next(x for x in ref['NASDAQ100の比ごとの最良'] if x.get('比') == 40)['名前']))
    rep = sc['five_mix_ndx の再現']
    sc['一致'] = bool(d_share < 1e-12 and d_cent < 1e-12 and all(sc['中身の業種が_rows_と一致'].values())
                    and rep['守りの条件を通った形']['この道具'] == rep['守りの条件を通った形']['five_mix_ndx']
                    and rep['答え']['この道具'] == rep['答え']['five_mix_ndx'] == REF_ANSWER
                    and abs(rep['答えの取り逃がしの最大']['この道具'] - rep['答えの取り逃がしの最大']['five_mix_ndx']) < 1e-9
                    and rep['芯40の最良']['この道具'] == rep['芯40の最良']['five_mix_ndx'] == name5(FORMS['芯40の最良']))
    log('自己検問', json.dumps(sc, ensure_ascii=False))
    if not sc['一致']:
        raise SystemExit('自己検問が通らない')

    # ── 形をそろえて測る ──
    nb = neighbors(PLAN)
    mine = {f'{JA[MINE_FROM]}→{JA[t]}': nb[f'{JA[MINE_FROM]}→{JA[t]}'] for t in MINE_TO}
    allf = dict(FORMS)
    for k, f in nb.items():
        allf[f'案の隣 {k}'] = f
    keys = list(allf)
    W = W_of(allf.values())
    ea, ba, ca, caa, ra = fast.eval(W), fbr.eval(W, a0), cent.eval(W), cent_alt.eval(W), realized(W, fast)
    wa = ((W / W.sum(axis=1, keepdims=True)) @ IND).sum(axis=1)
    ga = gates(ea, ba, ca, wa)
    Ga = dict(g1=ea['P15'], g2=ba['mean_pi'], g3=ca['c30med'], g4=ra['med'])
    rega, Ra, Rsa = regret_of(Ga)
    cka = checks_W(W)
    pos = {i: k for k, i in enumerate(order)}

    def core_rank(f):
        v = tuple(int(f.get(c, 0)) // STEP for c in FIVE)
        hit = np.where((F5 == np.array(v, dtype=np.int8)).all(axis=1))[0]
        if not len(hit):
            return dict(芯の形か=False)
        i = int(hit[0])
        return dict(芯の形か=True, 守りの条件を通ったか=bool(feas[i]), 順位=(pos[i] + 1 if i in pos else None), 母数=int(len(ii)))

    summ = {}
    for j, k in enumerate(keys):
        f = allf[k]
        summ[k] = dict(
            形=f, 名前=name5(f),
            元=dict(P15π=r(ea['P15'][j]), 平均=r(ea['mean_pi'][j]), 五パーセント未満=r(ea['P5'][j]), 最大下落=r(ea['mdd'][j], 1), ぶれ=r(ea['vol'][j], 1)),
            基礎率=dict(P15π=r(ba['P15'][j]), 平均=r(ba['mean_pi'][j]), 五パーセント未満=r(ba['P5'][j])),
            百年=dict(三十年の中央=round(float(ca['c30med'][j]), 3), 三十年の最悪=round(float(ca['c30min'][j]), 3),
                    本物のNASDAQ100をつないだ中央=round(float(caa['c30med'][j]), 3), 本物のNASDAQ100をつないだ最悪=round(float(caa['c30min'][j]), 3)),
            実績=dict(年15パーセント以上の割合=r(ra['share'][j], 1), 年率の中央=r(ra['med'][j]), 最悪=r(ra['worst'][j])),
            勝ち業種の中身の比重の合計=r(wa[j], 1),
            守りの条件={g: bool(v[j]) for g, v in ga.items()}, 守りの条件をすべて通った=bool(all(v[j] for v in ga.values()) and ea['ok'][j] and ba['ok'][j] and ca['ok'][j]),
            最終の確かめ=cka[j],
            取り逃がし={GOAL_JA[g]: round(float(rega[g][j]), 3) for g in GOALS}, 取り逃がしの最大=round(float(Ra[j]), 4),
            取り逃がしの合計=round(float(Rsa[j]), 4),
            芯の形の中の位置=core_rank(f))
    out = dict(generated=time.strftime('%Y-%m-%d'), tool='night/ndx40_form_check.py', kind='参考（配分は変えない・形と選び方は道具の頭に固定）',
               question='NASDAQ100 40 / SMH 25 / ITA 15 / XLV 10 / VBR 10 とあなたならどうする？', selfcheck=sc,
               芯の形の最良と最悪={GOAL_JA[g]: dict(最良=(round(best[g], 3) if g == 'g3' else r(best[g])),
                                             最悪=(round(worst[g], 3) if g == 'g3' else r(worst[g]))) for g in GOALS})
    out['形ごとの物差し'] = summ

    # 案の隣（案との差）
    jP = keys.index('案')
    nbt = []
    for k in nb:
        j = keys.index(f'案の隣 {k}')
        nbt.append(dict(移す=k, 名前=name5(nb[k]),
                        案との差=dict(元のP15π=r(ea['P15'][j] - ea['P15'][jP]), 元の平均=r(ea['mean_pi'][j] - ea['mean_pi'][jP], 3),
                                   元の5パーセント未満=r(ea['P5'][j] - ea['P5'][jP]), 最大下落=r(ea['mdd'][j] - ea['mdd'][jP], 1),
                                   基礎率の平均=r(ba['mean_pi'][j] - ba['mean_pi'][jP], 3), 基礎率の5パーセント未満=r(ba['P5'][j] - ba['P5'][jP]),
                                   百年の中央=round(float(ca['c30med'][j] - ca['c30med'][jP]), 3), 百年の最悪=round(float(ca['c30min'][j] - ca['c30min'][jP]), 3),
                                   実績の年率の中央=r(ra['med'][j] - ra['med'][jP]), 実績の年15パーセント以上=r(ra['share'][j] - ra['share'][jP], 1)),
                        取り逃がしの最大=round(float(Ra[j]), 4), 守りの条件をすべて通った=summ[f'案の隣 {k}']['守りの条件をすべて通った'],
                        最終の確かめ=cka[j]['合否']))
    out['案の隣'] = nbt

    # 私の答え（SMH 20 の縛り・浮いた5の行き先4通り）
    def pick(cands):
        ok = [k for k in cands if summ[k]['守りの条件をすべて通った'] and summ[k]['最終の確かめ']['合否']]
        if not ok:
            return None, ok
        jj = {k: keys.index(k) for k in ok}
        best_k = sorted(ok, key=lambda k: key_of(Ra[jj[k]], Rsa[jj[k]], Ga['g4'][jj[k]], Ga['g1'][jj[k]], ea['mdd'][jj[k]], summ[k]['名前']))[0]
        return best_k, ok
    mk = [f'案の隣 {k}' for k in mine]
    m_best, m_ok = pick(mk)
    out['私の答え'] = dict(
        決まり='SMH 20 の縛りを案に足し、浮いた5の行き先を NASDAQ100・ITA・XLV・VBR の4通りから（守りの条件4つと F1〜F3 を通った中で4つの目標の取り逃がしの最大が最小）',
        候補={k.replace('案の隣 ', ''): dict(名前=summ[k]['名前'], 取り逃がしの最大=summ[k]['取り逃がしの最大'], 取り逃がしの合計=summ[k]['取り逃がしの合計'],
                                         守りの条件をすべて通った=summ[k]['守りの条件をすべて通った'], 最終の確かめ=summ[k]['最終の確かめ']['合否']) for k in mk},
        通った候補=[k.replace('案の隣 ', '') for k in m_ok],
        答え=(summ[m_best]['名前'] if m_best else '案のまま（どの候補も通らない）'),
        案=dict(取り逃がしの最大=summ['案']['取り逃がしの最大'], 守りの条件をすべて通った=summ['案']['守りの条件をすべて通った'],
               最終の確かめ=summ['案']['最終の確かめ']['合否']))
    r_best, r_ok = pick(['案'] + [f'案の隣 {k}' for k in nb])
    out['参考_縛りなしで案と隣の21通りの最良'] = dict(答え=(summ[r_best]['名前'] if r_best else None),
                                         取り逃がしの最大=(summ[r_best]['取り逃がしの最大'] if r_best else None))
    log('私の答え', out['私の答え']['答え'], '／参考 縛りなし', out['参考_縛りなしで案と隣の21通りの最良'])

    # 詳しい物差し（主な形と私の答え）
    show = {k: allf[k] for k in FORMS}
    if m_best:
        show['私の答え'] = allf[m_best]
    if r_best and r_best not in show and allf[r_best] not in show.values():
        show['参考 縛りなしの最良'] = allf[r_best]
    assets = sorted({a for f in show.values() for a in f} | {'VOO'})
    with contextlib.redirect_stdout(io.StringIO()):
        mega = U.mega_map(rows, assets)
        tab0 = U.measure(show, rows, chains, mega=mega)[UC.W_CRASH]
        tj = U.measure(show, rows, ch_jpy, mega=mega, windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
        k4, _ = N.chips_adj(rows, assets)
        vt = N.variants(show, rows, chains, k4)[UC.W_CRASH]
    det = {}
    for nm, f in show.items():
        o = tab0[nm]
        det[nm] = dict(
            形=f, 名前=name5(f),
            元の物差し=dict(P15π=o['P15π'], 平均=o['π加重の平均の年率'], 五パーセント未満=o['P5π（5%未満）'], 最悪の世界=o['最悪の世界'],
                         最大下落=o['最大下落'], ぶれ=o['ぶれ'], 世界=o['世界ごとの年率'], 過去の転がる20年で15パーセント以上=o['過去の転がる20年で15%以上']),
            元の物差しの感度ごとの今との差={N.VARS_JA[v]: dict(P15=r(vt[nm][v]['P15'] - vt['今'][v]['P15']),
                                                     平均=r(vt[nm][v]['mean_pi'] - vt['今'][v]['mean_pi'], 3)) for v in N.VARS},
            円の枠={k: tj[nm][k] for k in ('π加重の平均の年率', 'P15π', 'P5π（5%未満）', '最大下落', '過去の転がる20年で15%以上')},
            中身の集中=B.lookthrough(f),
            物差しの外の実務_NISA=nisa_steady(f, tgt, cost_now))
        log(nm, json.dumps({k: det[nm][k] for k in ('元の物差し', '円の枠')}, ensure_ascii=False)[:400])
    out['詳しい物差し'] = det
    # 再現の確かめ（今・芯の答えの値が five_mix_ndx の詳しい物差しと同じ）
    rd = ref['詳しい物差し']
    chk = {}
    for nm, rk in (('今', '今'), ('芯の答え', '答え（芯・4つの目標）')):
        chk[nm] = dict(元のP15π=(det[nm]['元の物差し']['P15π'], rd[rk]['元の物差し']['P15π']),
                       基礎率の平均=(summ[nm]['基礎率']['平均'], rd[rk]['基礎率の物差し']['平均']),
                       百年の中央=(summ[nm]['百年']['三十年の中央'], rd[rk]['百年']['三十年の中央']),
                       実績の年率の中央=(summ[nm]['実績']['年率の中央'], rd[rk]['実績']['年率の中央']),
                       円の最大下落=(det[nm]['円の枠']['最大下落'], rd[rk]['円の枠']['最大下落']))
    ok_chk = all(a == b for v in chk.values() for a, b in v.values())
    sc['今と芯の答えの値が_five_mix_ndx_と同じ'] = dict(値=chk, 一致=bool(ok_chk))
    if not ok_chk:
        raise SystemExit('今・芯の答えの値が five_mix_ndx と合わない: ' + json.dumps(chk, ensure_ascii=False))
    out['secs'] = round(time.time() - t0)
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    log('→', OUT, out['secs'], 's')


if __name__ == '__main__':
    main()
