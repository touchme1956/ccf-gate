#!/usr/bin/env python3
"""night/balance_check.py — 半導体を厚くしないバランスのよい形（2026-11-22・参考の測り）

ユーザー「もっとバランスのいいポートフォリオない？半導体多すぎではない？」
読み方（固定）: 枝のリターン寄りの案（ETF 側 NASDAQ100 40 / SMH 30 / ITA 15 / FBT 10 / VBR 5）は半導体が厚い。
  半導体を厚くせず、4つの物差しのどれでも大きく負けない形（＝バランス）を探す。
この道具は門・採点・配分（portfolio.json）・注文書に触れない（測って選ぶだけ。配分に入れるのは別の手順）。
★形・条件・目的・最終の確かめはこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする。
  見たもの: ret_seek_check の数字（私の案・今の形・11-09・枝の案・目的の上位10）と、各 ETF の中身の半導体の割合
  （QQQM 31.93%・SMH 91.62%・VBR 0.56%・ITA・XLV・FBT 0%）。半導体の線の中の候補の形の物差しの数字は見ていない。

訂正（集中の数え方）: ret_seek_check は中身の集中を「ETF 側100%＋個別株10%＝資産の110%」で数えていた（NVDA と半導体の連鎖を約1割多く出す）。
  この道具は資産全体で数える＝ETF 側×0.9 ＋ 個別株10%（席5社×2%・席は unx_assets.castle_copy）。

形の範囲（ret_seek_check と同じ）: 6本（QQQM・SMH・ITA・XLV・FBT・VBR）・5%刻み・合計100（ETF 側）・各本は0か5%以上・
  NASDAQ100 が最大の1本 ∧ 40%以上60%以下（芯）
今の形＝main の配分（ETF 側 NASDAQ100 45 / SMH 20 / ITA 10 / FBT 15 / VBR 10・個別株10）。origin/main の portfolio.json と照合・違えば止まる。
  枝の portfolio.json が枝の案と違っても止まる。
条件:
  H 半導体の線: 半導体の連鎖（下限・資産全体）が「ETF 側を NASDAQ100 だけにした形」以下
     ＝全体の半導体を芯の NASDAQ100 そのものより濃くしない（SMH で足した分は、半導体を持たない本で薄めた分まで）。
     値は 4.0（席の LRCX・ASML）＋0.9×31.93＝32.74%。今の形 33.47%（線の少し上）・私の案 32.06%・枝の案 40.26%。
  守り（今の形と比べる・five_mix と同じ4つ）: ①基礎率の物差しの5%未満 ≤ 今 ②最大下落 ≥ 今（浅い）③100年の代用の30年の最悪 ≥ 今
     ④勝ち業種の中身の比重の合計 ≤ 今
目標（4つ・five_mix_ndx と同じ）: g1 元の物差しの P15π・g2 基礎率の物差しの平均・g3 100年の代用の30年の中央・
  g4 実績の20年の積立の年率の中央（2000-09〜）
選び方（five_mix_ndx と同じ）: 条件を通った形の中で目標ごとに 取り逃がし＝(最良−その形)÷(最良−最悪)・4つの最大を最小に。
  小数3桁に丸めて同じなら 取り逃がしの合計 → g4 → g1 → 最大下落が浅い → 名前の順
最終の確かめ（five_mix_ndx と同じ・今の形と比べる）: F1 基礎率の感度6本すべてで 平均 ≥ 今 ∧ 5%未満 ≤ 今／F2 円の最大下落 ≥ 今／
  F3 小型バリューの上乗せなし（S2）で基礎率の5%未満 ≤ 今。上位30を順に・最初に通った形を答えに。通らなければ「決まりを満たす形は無い」
併せて出す（判定に使わない）:
  半導体の線を外した同じ決まりの答え（線が何を変えたか）／SMH の比ごと（0〜30%）の最良（芯の縛りだけ・同じ4つの目標をその比の中で・
  条件と F1〜F3 は合否の印だけ）／詳しい物差し（答え・今の形・枝の案・私の案・11-09・ETF 側を NASDAQ100 だけ）＝元（平均・P15π・P20・
  5%未満・最悪の世界・ぶれ・最大下落・世界ごと）・感度5本の今との差・円・基礎率（平均・5%未満・感度6本の今との差）・100年・実績・
  集中（半導体の連鎖・NVDA・最大の1銘柄＝lookthrough.py に資産全体で渡す）／参考 S&P500（VOO だけ・out/sp500_compare.json）の半導体の連鎖と NVDA
回帰の検査: (a) Fast が measure と 1e-9 以内（今の形・枝の案・私の案）(b) 感度の主が measure と 1e-9 以内 (c) 実績の割合が past20 と一致
  (d) 表示の値が ret_seek と一致（平均 今 10.83・枝 11.08・私の案 10.76 を ±0.051・P15π 26.75・28.5・25.35 を ±0.15）
  (e) 線形で出す半導体の連鎖・NVDA が lookthrough.py（資産全体で渡す）と一致（半導体 ±0.051・NVDA ±0.0051）。どれかが外れれば止める
⚠ 限界: 線（芯の NASDAQ100 の濃さ）・守りの条件・4つの目標を等しく扱うのは私が決めた／未来の世界は予想・分散の上乗せは仮定／
  実績は一つの時代（テックと半導体が勝った26年）／100年の写しの NASDAQ100 は業種を固定した代わり／
  中身は 2026-09〜10 の写し（NASDAQ100 の中の半導体の割合は時価で動く）／物差しは ETF 側だけ（個別株は外）／
  形どうしの差の多くは雑音に近い／税と NISA の枠は物差しに入らない
使い方: python3 night/balance_check.py → out/balance_check.json
"""
import contextlib, io, json, os, re, subprocess, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'balance_check.json')

import best15_check as B   # noqa: E402
import best15r_check as BR  # noqa: E402
from five_mix_ndx_check import realized  # noqa: E402
import ret_seek_check as RS  # noqa: E402

SIX, JA, name, whole, grid, r = RS.SIX, RS.JA, RS.name, RS.whole, RS.grid, RS.r
NOWF = {'QQQM': 45, 'SMH': 20, 'ITA': 10, 'FBT': 15, 'VBR': 10}
RETF = {'QQQM': 40, 'SMH': 30, 'ITA': 15, 'FBT': 10, 'VBR': 5}
BASEF = {'QQQM': 40, 'SMH': 20, 'ITA': 15, 'XLV': 10, 'VBR': 15}
F1109 = {'QQQM': 50, 'SMH': 20, 'ITA': 15, 'FBT': 15}
NDXF = {'QQQM': 100}
CASTLE_PCT, STEP = 10, 5
K = (100 - CASTLE_PCT) / 100
GOALS = ['g1', 'g2', 'g3', 'g4']
GOAL_JA = {'g1': '元の物差しの P15π', 'g2': '基礎率の物差しの平均', 'g3': '100年の代用の30年の中央',
           'g4': '実績の20年の積立の年率の中央（2000-09〜）'}
SDEC, NFIN, EPS = 3, 30, 1e-12
K_NOW, K_RET, K_BASE, K_1109, K_NDX = '今の形（main）', '枝の案（リターン寄り）', '私の案（11-22 の前）', '11-09 の形', 'ETF 側を NASDAQ100 だけ'
SHOWN = {K_NOW: (10.83, 26.75), K_RET: (11.08, 28.5), K_BASE: (10.76, 25.35)}


def log(*a):
    print('[balance]', *a, file=sys.stderr, flush=True)


def etf_side(tgt):
    w = {('QQQM' if k == 'IFREE-NDX' else k): float(v) for k, v in tgt['ami_weights'].items() if v}
    tot = sum(w.values())
    return {k: 100 * v / tot for k, v in w.items()}, float(tgt.get('shiro_castle_pct') or 0)


def same(w, f):
    return all(abs(w.get(k, 0) - f.get(k, 0)) < 1e-6 for k in set(w) | set(f))


def main():
    t0 = time.time()
    # ── 正本との照合 ──
    live = json.loads(subprocess.run(['git', 'show', 'origin/main:portfolio.json'], capture_output=True, text=True,
                                     cwd=BASE, check=True).stdout)['target']
    brt = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    for nm, t, f in [(K_NOW, live, NOWF), (K_RET, brt, RETF)]:
        w, cp = etf_side(t)
        if not same(w, f) or cp != CASTLE_PCT:
            raise SystemExit(f'{nm} が正本と違う: {w} 個別株 {cp}')

    import lookthrough as L
    import unx_assets as U
    import upside_check as UC
    import bestpf_check as BC
    import bestpf_eval as E
    import etf_forward_combo as CB
    import ndx_swap_check as N
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    P = BR.POOL
    for c in SIX + ['VOO']:
        if c not in P or c not in rows:
            raise SystemExit(f'物差しに無い本: {c}')
    B.century_extend(U)
    fast, cent = B.Fast(U, rows, chains, P), B.Cent(U, P)
    fbr = BR.FastBR(fast)
    st = BR.industry_state()
    vec, vchk = BR.industry_vectors(U, rows)
    win = list(dict.fromkeys(st['top5'] + st['rec']))
    IND = np.array([[(st['mkt'].get(k, 0.0) if c == 'VOO' else vec.get(c, {}).get(k, 0.0)) for k in win] for c in P])
    adj = {nm: BR.adj_vector(vec, st, rt, P)[0] for nm, rt in BR.RATES.items()}
    a0 = adj['主（20年の値）']

    def W_of(forms):
        return np.array([[f.get(c, 0) for c in P] for f in forms], dtype=np.float64)

    # ── 中身（線形）: 各 ETF の半導体の割合・未取得・NVDA。席は5社×2% ──
    prof = L.jload(os.path.join(BASE, 'out', 'etf_profiles.json')) or {}
    share = {}
    for c in SIX:
        look, unk = L.explode({c: 1e6}, prof)
        share[c] = dict(semi=sum(v for t, v in look.items() if t in L.SEMI) / 1e6, unk=sum(unk.values()) / 1e6,
                        nvda=look.get('NVDA', 0.0) / 1e6)
    _, seats, _ = U.castle_copy()
    seats = list(seats)
    per = CASTLE_PCT / len(seats)
    c_semi = per * sum(1 for s in seats if s in L.SEMI)
    c_nvda = per * sum(1 for s in seats if s == 'NVDA')
    sv = np.array([share[c]['semi'] for c in SIX])
    uv = np.array([share[c]['unk'] for c in SIX])
    nv = np.array([share[c]['nvda'] for c in SIX])

    def conc(f):
        w = np.array([f.get(c, 0) for c in SIX], dtype=np.float64)
        w = 100 * w / w.sum()
        lo = c_semi + K * float(w @ sv)
        return dict(lo=lo, hi=lo + K * float(w @ uv), nvda=c_nvda + K * float(w @ nv))

    N.CASTLE_ARG = ','.join(f'{s}={per:g}' for s in seats)
    N.NET_ARG['VBR'] = 'VBR'

    def look_whole(f):
        lk = N.lookthrough({c: v * K for c, v in f.items() if v})
        m = re.match(r'([\d.]+)〜([\d.]+)%', lk.get('半導体の連鎖（下限〜上限）', ''))
        return lk, (float(m.group(1)) if m else None), (float(m.group(2)) if m else None)

    # ── 参照の形と回帰の検査 ──
    REF = {K_NOW: NOWF, K_RET: RETF, K_BASE: BASEF}
    Wr = W_of(REF.values())
    er = fast.eval(Wr)
    assets0 = sorted({a for f in REF.values() for a in f} | {'VOO'})
    with contextlib.redirect_stdout(io.StringIO()):
        tab0 = U.measure(dict(REF), rows, chains, mega=U.mega_map(rows, assets0))[UC.W_CRASH]
        k40, _ = N.chips_adj(rows, assets0)
        vt0 = N.variants(dict(REF), rows, chains, k40)[UC.W_CRASH]
    reg = {}
    for j, k in enumerate(REF):
        raw = tab0[k]['_raw']
        reg[k] = dict(P15=abs(float(er['P15'][j]) - raw['P15']), 平均=abs(float(er['mean_pi'][j]) - raw['mean_pi']),
                      最大下落=abs(float(er['mdd'][j]) - raw['mdd']), 感度の主の平均=abs(vt0[k]['main']['mean_pi'] - raw['mean_pi']))
    rz0 = realized(Wr, fast)
    reg['実績の割合と_past20'] = float(np.max(np.abs(rz0['share'] - er['past20'])))
    shown = {k: dict(平均=tab0[k]['π加重の平均の年率'], P15π=tab0[k]['P15π']) for k in REF}
    ok_num = all(v < 1e-9 for k in REF for v in reg[k].values()) and reg['実績の割合と_past20'] < 1e-9
    ok_shown = all(abs(shown[k]['平均'] - SHOWN[k][0]) < 0.051 and abs(shown[k]['P15π'] - SHOWN[k][1]) < 0.15 for k in REF)
    lkchk = {}
    for k, f in {**REF, K_NDX: NDXF}.items():
        lk, lo, hi = look_whole(f)
        cc = conc(f)
        lkchk[k] = dict(線形=dict(下限=round(cc['lo'], 3), 上限=round(cc['hi'], 3), NVDA=round(cc['nvda'], 4)),
                        lookthrough=dict(下限=lo, 上限=hi, NVDA=lk.get('NVDA（資産全体）')),
                        一致=bool(lo is not None and abs(cc['lo'] - lo) < 0.051 and hi is not None and abs(cc['hi'] - hi) < 0.051
                                and lk.get('NVDA（資産全体）') is not None and abs(cc['nvda'] - lk['NVDA（資産全体）']) < 0.0051))
    ok_lk = all(v['一致'] for v in lkchk.values())
    if not (ok_num and ok_shown and ok_lk):
        raise SystemExit(f'回帰の検査が通らない: {reg} {shown} {lkchk}')
    log('回帰の検査 ✓', shown, {k: v['線形'] for k, v in lkchk.items()})
    line = conc(NDXF)['lo']

    # ── 形の範囲と条件 ──
    Gd = grid()
    ix = [P.index(c) for c in SIX]
    A = np.zeros((len(Gd), len(P)), dtype=np.float64)
    A[:, ix] = Gd
    form = [{cc: int(v) * STEP for cc, v in zip(SIX, row) if v} for row in Gd]
    names = [name(f) for f in form]
    W0 = W_of([NOWF])
    e, b, c, rz = fast.eval(A), fbr.eval(A, a0), cent.eval(A), realized(A, fast)
    e0, b0, c0, rzn = fast.eval(W0), fbr.eval(W0, a0), cent.eval(W0), realized(W0, fast)
    An = A / A.sum(axis=1, keepdims=True)
    winsum = (An @ IND).sum(axis=1)
    semi = c_semi + K * ((Gd * STEP) @ sv)
    semi_hi = semi + K * ((Gd * STEP) @ uv)
    nvda = c_nvda + K * ((Gd * STEP) @ nv)
    now = dict(g1=float(e0['P15'][0]), g2=float(b0['mean_pi'][0]), g3=float(c0['c30med'][0]), g4=float(rzn['med'][0]),
               P5b=float(b0['P5'][0]), mdd=float(e0['mdd'][0]), c30min=float(c0['c30min'][0]),
               win=float(((W0 / W0.sum()) @ IND).sum()), semi=conc(NOWF)['lo'])
    Gs = dict(g1=e['P15'], g2=b['mean_pi'], g3=c['c30med'], g4=rz['med'])
    meas = e['ok'] & b['ok'] & c['ok']
    with np.errstate(invalid='ignore'):
        H = semi <= line + 1e-9
        gate = {'①基礎率の5%未満': b['P5'] <= now['P5b'] + EPS, '②最大下落': e['mdd'] >= now['mdd'] - EPS,
                '③100年の最悪': c['c30min'] >= now['c30min'] - EPS, '④勝ち業種の中身の比重の合計': winsum <= now['win'] + 1e-9}
    guard = meas.copy()
    for v in gate.values():
        guard &= v
    feas = guard & H
    counts = dict(形の数=len(Gd), 測れない=int((~meas).sum()), H半導体の線で外れた=int((meas & ~H).sum()),
                  **{f'{k}で外れた（測れた形の中）': int((meas & ~v).sum()) for k, v in gate.items()},
                  守りの4つを通った=int(guard.sum()), 守りとHを通った=int(feas.sum()))
    log('条件', counts)

    def regrets(idx):
        best = {g: float(np.max(Gs[g][idx])) for g in GOALS}
        worst = {g: float(np.min(Gs[g][idx])) for g in GOALS}
        rg = {g: (best[g] - Gs[g]) / (best[g] - worst[g]) if best[g] - worst[g] > EPS else np.zeros(len(A)) for g in GOALS}
        return best, worst, rg, np.maximum.reduce([rg[g] for g in GOALS]), sum(rg[g] for g in GOALS)

    def order(idx, R_, Rs_):
        return sorted(list(idx), key=lambda i: (round(float(R_[i]), SDEC), round(float(Rs_[i]), 9), -float(Gs['g4'][i]),
                                                -float(Gs['g1'][i]), -float(e['mdd'][i]), names[i]))

    def brief(i, rg=None, R_=None):
        out = dict(名前=names[i], 形=form[i], 全体の比=whole(form[i]),
                   元のP15π=r(100 * e['P15'][i]), 元の平均=r(100 * e['mean_pi'][i]), 元の5パーセント未満=r(100 * e['P5'][i]),
                   最大下落=r(100 * e['mdd'][i], 1), 基礎率の平均=r(100 * b['mean_pi'][i]), 基礎率の5パーセント未満=r(100 * b['P5'][i]),
                   百年の中央=r(c['c30med'][i], 3), 百年の最悪=r(c['c30min'][i], 3),
                   実績の年率の中央=r(100 * rz['med'][i]), 実績の年15パーセント以上の割合=r(100 * rz['share'][i], 1),
                   半導体の連鎖=f'{semi[i]:.1f}〜{semi_hi[i]:.1f}%', NVDA=r(nvda[i]), 勝ち業種の中身の比重の合計=r(100 * winsum[i], 1),
                   条件={'H半導体の線': bool(H[i]), **{k: bool(v[i]) for k, v in gate.items()}})
        if rg is not None:
            out.update(取り逃がしの最大=round(float(R_[i]), 4), 取り逃がし={g: round(float(rg[g][i]), 3) for g in GOALS})
        return out

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

    def checks(idx, rg=None, R_=None):
        if not idx:
            return []
        Wt = A[idx]
        vres = {v: (ve(Wt, v), ve(W0, v)) for v in BR.VARS}
        _, _, mdd_j = CB.path_stats((Wt / Wt.sum(axis=1, keepdims=True)) @ Gj, Gj.shape[1])
        Ss = s2(Wt)
        out = []
        for j, i in enumerate(idx):
            ok1 = all(vres[v][0]['mean_pi'][j] >= vres[v][1]['mean_pi'][0] - EPS and vres[v][0]['P5'][j] <= vres[v][1]['P5'][0] + EPS
                      for v in BR.VARS)
            ok2 = bool(mdd_j[j] >= mdd_j0[0] - EPS)
            ok3 = bool(Ss['P5'][j] <= S0['P5'][0] + EPS)
            out.append(dict(**brief(i, rg, R_), F1=bool(ok1), F2円の最大下落=ok2, F3小型バリューの上乗せなしの5パーセント未満=ok3,
                            合否=bool(ok1 and ok2 and ok3), 円の最大下落=r(100 * mdd_j[j], 1),
                            感度ごとの今との差={v: dict(平均=r(100 * (vres[v][0]['mean_pi'][j] - vres[v][1]['mean_pi'][0]), 3),
                                                    五パーセント未満=r(100 * (vres[v][0]['P5'][j] - vres[v][1]['P5'][0])))
                                           for v in BR.VARS}))
        return out

    def choose(mask):
        idx = np.where(mask)[0]
        if not len(idx):
            return None, [], None
        best, worst, rg, R_, Rs_ = regrets(idx)
        top = order(idx, R_, Rs_)[:NFIN]
        fin = checks(top, rg, R_)
        ans = next((x for x in fin if x['合否']), None)
        bw = {GOAL_JA[g]: dict(最良=r((1 if g == 'g3' else 100) * best[g], 3), 最悪=r((1 if g == 'g3' else 100) * worst[g], 3)) for g in GOALS}
        return ans, fin, bw

    ans, fin, bw = choose(feas)
    ans_noH, fin_noH, bw_noH = choose(guard)
    log('答え', ans['名前'] if ans else None, '／線なし', ans_noH['名前'] if ans_noH else None)

    # SMH の比ごと（芯の縛りだけ・その比の中で4つの目標・条件と F1〜F3 は印だけ）
    js = SIX.index('SMH')
    front = []
    for u in range(0, 7):
        sel = meas & (Gd[:, js] == u)
        idx = np.where(sel)[0]
        if not len(idx):
            front.append(dict(SMH=u * STEP, 形の数=0))
            continue
        _, _, rg, R_, Rs_ = regrets(idx)
        i = order(idx, R_, Rs_)[0]
        front.append(dict(SMH=u * STEP, 形の数=int(len(idx)), 守りの4つを通った形=int((guard & sel).sum()), **checks([i], rg, R_)[0]))

    # ── 詳しい物差し ──
    DET = {}
    if ans:
        DET['答え'] = ans['形']
    DET.update({K_NOW: NOWF, K_RET: RETF, K_BASE: BASEF, K_1109: F1109, K_NDX: NDXF})
    if ans_noH and (not ans or ans_noH['名前'] != ans['名前']):
        DET['半導体の線を外した答え'] = ans_noH['形']
    Wd = W_of(DET.values())
    ed, bd, cd, rzd = fast.eval(Wd), fbr.eval(Wd, a0), cent.eval(Wd), realized(Wd, fast)
    Vd = {v: ve(Wd, v) for v in BR.VARS}
    assets = sorted({a for f in DET.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)
    with contextlib.redirect_stdout(io.StringIO()):
        tab = U.measure(dict(DET), rows, chains, mega=mega)[UC.W_CRASH]
        tj = U.measure(dict(DET), rows, ch_jpy, mega=mega, windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
        k4, _ = N.chips_adj(rows, assets)
        vtd = N.variants(dict(DET), rows, chains, k4)[UC.W_CRASH]
    _, sim = U.tables()
    pi, _, _ = E.load_pi()
    jn = list(DET).index(K_NOW)
    detail = {}
    for j, k in enumerate(DET):
        t = tab[k]
        q, pr_ = UC.upside(sim, t['_raw'], pi)
        lk, lo, hi = look_whole(DET[k])
        detail[k] = dict(
            形=DET[k], 名前=name(DET[k]), 全体の比=whole(DET[k]),
            元=dict(平均=t['π加重の平均の年率'], P15π=t['P15π'], P20_道の束=pr_.get('P20（道の束）'), 五パーセント未満=t['P5π（5%未満）'],
                   元本割れ=t['P0π（元本割れ）'], 最悪の世界=t['最悪の世界'], ぶれ=t['ぶれ'], 最大下落=t['最大下落'],
                   世界ごとの年率=t['世界ごとの年率'], 内部収益率の分位=q, 過去の転がる20年で15パーセント以上=t['過去の転がる20年で15%以上']),
            感度5本の今との差={N.VARS_JA[v]: round(100 * (vtd[k][v]['mean_pi'] - vtd[K_NOW][v]['mean_pi']), 3) for v in N.VARS},
            円=dict(平均=tj[k]['π加重の平均の年率'], P15π=tj[k]['P15π'], 最大下落=tj[k]['最大下落']),
            基礎率=dict(平均=r(100 * bd['mean_pi'][j]), P15π=r(100 * bd['P15'][j]), 五パーセント未満=r(100 * bd['P5'][j]),
                     感度6本の今との差={v: r(100 * (Vd[v]['mean_pi'][j] - Vd[v]['mean_pi'][jn]), 3) for v in BR.VARS}),
            百年=dict(三十年の中央=r(cd['c30med'][j], 3), 三十年の最悪=r(cd['c30min'][j], 3)),
            実績=dict(年15パーセント以上の割合=r(100 * rzd['share'][j], 1), 年率の中央=r(100 * rzd['med'][j])),
            集中=dict(半導体の連鎖=lk.get('半導体の連鎖（下限〜上限）'), NVDA=lk.get('NVDA（資産全体）'), 最大の1銘柄=lk.get('最大の1銘柄'),
                    線形の検算=dict(下限=round(conc(DET[k])['lo'], 2), NVDA=round(conc(DET[k])['nvda'], 3)),
                    城=f'{N.CASTLE_ARG}（席{len(seats)}社×{per:g}%）', 数え方='資産全体（ETF 側×0.9＋個別株10%）'))

    sp = json.load(open(os.path.join(BASE, 'out', 'sp500_compare.json')))['results']['中身の集中']['S&P500（VOO）']
    out = dict(
        generated=time.strftime('%Y-%m-%d'), tool='night/balance_check.py',
        kind='参考（測って選ぶだけ・形・条件・選び方は道具の頭に固定し回す前にコミット）',
        question='もっとバランスのいいポートフォリオない？半導体多すぎではない？',
        reading='枝のリターン寄りの案は半導体が厚い。半導体を芯の NASDAQ100 より濃くせず、4つの物差しのどれでも大きく負けない形を探す',
        訂正=dict(内容='ret_seek_check は中身の集中を ETF 側100%＋個別株10%（資産の110%）で数えていた。ここでは資産全体（ETF 側×0.9＋個別株10%）',
                 正しい値={k: lkchk[k]['lookthrough'] for k in lkchk}),
        regression=dict(差=reg, 表示=shown, 中身の検算=lkchk, 通過=True),
        中身の割合={c: {kk: round(100 * vv, 3) for kk, vv in share[c].items()} for c in SIX},
        席=dict(社=seats, 一社=per, 半導体=c_semi),
        lines=dict(H_半導体の線=round(line, 3), 今の形の半導体=round(now['semi'], 3),
                   今の形=dict(基礎率の5パーセント未満=r(100 * now['P5b']), 最大下落=r(100 * now['mdd'], 1), 百年の最悪=r(now['c30min'], 3),
                             勝ち業種の中身の比重の合計=r(100 * now['win'], 1)),
                   勝ち業種=win),
        counts=counts,
        答え=(ans if ans else '決まりを満たす形は無い'), 最良と最悪=bw, 最終の確かめ=fin,
        半導体の線を外した答え=(ans_noH if ans_noH else '決まりを満たす形は無い'), 最終の確かめ_線なし=fin_noH, 最良と最悪_線なし=bw_noH,
        SMHの比ごとの最良=front,
        詳しい物差し=detail,
        参考_SP500=dict(半導体の連鎖=sp.get('半導体の連鎖（lookthrough と同じ SEMI）'), NVDA=sp.get('NVDA'), 出所=sp.get('出所'),
                      数え方='VOO だけ（個別株なし）'),
        caveats=['線（芯の NASDAQ100 の濃さ）・守りの条件・4つの目標を等しく扱うのは私が決めた', '未来の世界は予想・分散の上乗せは仮定',
                 '実績は一つの時代（テックと半導体が勝った26年）', '100年の写しの NASDAQ100 は業種を固定した代わり',
                 '中身は 2026-09〜10 の写し', '物差しは ETF 側だけ（個別株は外）', '形どうしの差の多くは雑音に近い', '税と NISA の枠は物差しに入らない'],
        secs=round(time.time() - t0))
    with open(OUT, 'w') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=str)
    log('→', OUT, '答え', ans['名前'] if ans else None, f'{out["secs"]}s')


if __name__ == '__main__':
    main()
