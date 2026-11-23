#!/usr/bin/env python3
"""night/ret_seek_check.py — 私の案を「これからリターンを取りに行く構成」に直す（2026-11-22・参考の測り）

ユーザー「NASDAQ100 40 / SMH 20 / ITA 15 / XLV 10 / VBR 15これからリターンを取りに行く構成に直して」
読み方（固定）: 11-22 に私が選んだ形（下げの浅さを優先した守り寄りの形）をもとに、期待のリターンを上げる形へ直す。
この道具は門・採点・配分（portfolio.json）・注文書に触れない（測って選ぶだけ。配分に入れるのは別の手順）。
★形・条件・目的・最終の確かめはこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする
  （私の案・今の形・11-09 の形の数字は前の答えで見ている。候補の数字はまだ見ていない）。

基の形（私の案）: QQQM 40 / SMH 20 / ITA 15 / XLV 10 / VBR 15（ETF 側。全体では個別株10%を除いた90%をこの比で）
今の形（portfolio.json と照合・違えば止まる）: QQQM 45 / SMH 20 / ITA 10 / FBT 15 / VBR 10・個別株10
形の範囲:
  本＝私の案の5本＋今の形で持っている FBT（QQQM・SMH・ITA・XLV・FBT・VBR）・5%刻み・合計100（ETF 側）・各本は0か5%以上
  芯＝NASDAQ100 が最大の1本（他のどの本以上・同じ比は可）∧ 40%以上60%以下
      （five_mix_ndx の芯の縛りの下限を私の案の40へ上げた＝芯は下げない。つみたて投資枠・こどもNISA・iDeCo が自動で買うのも NASDAQ100）
条件（主の枠＝USD・崩れあり・元の物差しか100年の代用で測れない形は外す）:
  C1 下げの線: 最大下落が 11-09 の形（NASDAQ100 50 / SMH 20 / ITA 15 / FBT 15）以上に浅い
     （この1か月〔10-22〜11-22〕に main へ入れた形のうち最も深い下げ＝すでに受け入れた深さまで）
  C2 100年の代用: 30年の積立（起点1965〜1995）の市場との比の最悪 ≥ 1.00（どの起点でも市場に負けない＝壊れない複利の線）
  C3 年15%以上の確率（P15π）が私の案より上
目的: π加重の平均の年率（元の物差しの期待リターン）が最大。小数2桁（%）に丸めて同じなら P15π が高い → 最大下落が浅い → 名前の順
最終の確かめ（目的の順に上から・最初に通った形が答え）:
  F1 これから: 感度5本（主・A2〔直近15年〕を外す・半導体の基礎率・分散の上乗せなし・共分散をA2の窓から）のすべてで
     平均の年率が私の案より上（＝上乗せが直近15年の繰り返しや半導体の時代の続きだけに頼らない）
  F2 円: 円の枠（崩れあり）で平均の年率が私の案より上
  条件を通った形がすべて落ちたら「決まりを満たす形は無い」とし、目的の1位と外れた条件を名指しする
併せて出す（判定に使わない）: 答え・私の案・今の形・11-09 の形・目的の1位の詳しい物差し（P15π・P20（道の束）・内部収益率の分位・
  5%未満・最悪の世界・ぶれ・最大下落・世界ごとの年率・円の枠・業種の基礎率の物差し〔平均・5%未満・感度6本の私の案との差〕・
  100年の代用・実績〔2000-09〜の転がる20年の積立: 年15%以上の割合・年率の中央〕・中身の集中〔NVDA・半導体の連鎖・城は席の社で個別株10%〕）／
  FBT を使わない（私の案の5本だけ）同じ決まりの答え／NASDAQ100 の比ごとの目的の1位（最終の確かめ前）／条件ごとに外れた形の数／
  答えの全体の%（個別株10%を入れた形＝ETF 側×0.9）
回帰の検査: (a) 元の物差しの速い評価（best15_check.Fast）が unx_assets.measure と 1e-9 以内（私の案・今の形）
  (b) 感度の主（ndx_swap_check.variants）が measure と 1e-9 以内 (c) 実績の割合が Fast の past20 と一致
  (d) 私の案・今の形の表示の値が前の答え（平均 10.76 / 10.83・P15π 25.35 / 26.75 前後）と小数1桁で一致。どれかが外れれば止める
⚠ 限界: 未来の世界は予想・分散の上乗せは仮定・実績は一つの時代（テックと半導体が勝った26年）・100年の写しの NASDAQ100 は業種を固定した代わり・
  C1 の線と芯の縛りと条件は私が決めた・形どうしの差の多くは雑音に近い・税と NISA の枠は物差しに入らない
使い方: python3 night/ret_seek_check.py → out/ret_seek_check.json
"""
import contextlib, io, itertools, json, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'ret_seek_check.json')

import best15_check as B   # noqa: E402
import best15r_check as BR  # noqa: E402
from five_mix_ndx_check import realized  # noqa: E402

SIX = ['QQQM', 'SMH', 'ITA', 'XLV', 'FBT', 'VBR']
JA = {'QQQM': 'NASDAQ100', 'SMH': 'SMH', 'ITA': 'ITA', 'XLV': 'XLV', 'FBT': 'FBT', 'VBR': 'VBR'}
BASEF = {'QQQM': 40, 'SMH': 20, 'ITA': 15, 'XLV': 10, 'VBR': 15}
NOWF = {'QQQM': 45, 'SMH': 20, 'ITA': 10, 'FBT': 15, 'VBR': 10}
F1109 = {'QQQM': 50, 'SMH': 20, 'ITA': 15, 'FBT': 15}
CASTLE_PCT = 10
UNITS, STEP = 20, 5
NDX_LO, NDX_HI = 8, 12          # 40〜60%
TIE, EPS, BATCH = 1e-4, 1e-12, 40
K_BASE, K_NOW, K_1109 = '私の案', '今の形', '11-09 の形'


def log(*a):
    print('[ret_seek]', *a, file=sys.stderr, flush=True)


def name(f):
    return ' / '.join(f'{JA[c]} {f[c]:g}' for c in SIX if f.get(c))


def whole(f):
    k = (100 - CASTLE_PCT) / 100
    return {**{JA[c]: round(f[c] * k, 2) for c in SIX if f.get(c)}, '個別株': CASTLE_PCT}


def grid():
    out = []
    for v in itertools.product(range(0, NDX_HI + 1), repeat=len(SIX)):
        if sum(v) != UNITS:
            continue
        n = v[0]
        if n < NDX_LO or any(x > n for x in v[1:]):
            continue
        out.append(v)
    return np.array(out, dtype=np.int16)


def r(x, d=2):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), d)


def main():
    t0 = time.time()
    tgt = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    w = {('QQQM' if k == 'IFREE-NDX' else k): float(v) for k, v in tgt['ami_weights'].items() if v}
    tot = sum(w.values())
    w = {k: 100 * v / tot for k, v in w.items()}
    if any(abs(w.get(k, 0) - NOWF.get(k, 0)) > 1e-6 for k in set(w) | set(NOWF)) or float(tgt.get('shiro_castle_pct') or 0) != CASTLE_PCT:
        raise SystemExit(f'今の形が正本と違う: {w} 個別株 {tgt.get("shiro_castle_pct")}')
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
    vec, vchk = BR.industry_vectors(U, rows)
    st = BR.industry_state()
    adj = {nm: BR.adj_vector(vec, st, rt, P)[0] for nm, rt in BR.RATES.items()}
    a0 = adj['主（20年の値）']

    def W_of(forms):
        return np.array([[f.get(c, 0) for c in P] for f in forms], dtype=np.float64)

    def br_all(W):
        return {'主': fbr.eval(W, a0), '10年の値': fbr.eval(W, adj['10年の値']),
                '1位の業種を強く': fbr.eval(W, adj['1位の業種を強く（10年の値・Chips −4.0）']),
                '主の半分': fbr.eval(W, adj['主の半分']), '分散の上乗せなし': fbr.eval(W, a0, nobonus=True),
                '共分散をA2の窓から': fbr.eval(W, a0, cov2=True)}

    # ── 参照の形と回帰の検査 ──
    REF = {K_BASE: BASEF, K_NOW: NOWF, K_1109: F1109}
    Wr = W_of(REF.values())
    er, cr = fast.eval(Wr), cent.eval(Wr)
    assets0 = sorted({a for f in REF.values() for a in f} | {'VOO'})
    mega0 = U.mega_map(rows, assets0)
    with contextlib.redirect_stdout(io.StringIO()):
        tab0 = U.measure(dict(REF), rows, chains, mega=mega0)[UC.W_CRASH]
    k40, _ = N.chips_adj(rows, assets0)
    vt0 = N.variants(dict(REF), rows, chains, k40)[UC.W_CRASH]
    reg = {}
    for j, k in enumerate(REF):
        raw = tab0[k]['_raw']
        reg[k] = dict(P15=abs(float(er['P15'][j]) - raw['P15']), 平均=abs(float(er['mean_pi'][j]) - raw['mean_pi']),
                      最大下落=abs(float(er['mdd'][j]) - raw['mdd']), 感度の主の平均=abs(vt0[k]['main']['mean_pi'] - raw['mean_pi']))
    rz0 = realized(Wr, fast)
    reg['実績の割合と_past20'] = float(np.max(np.abs(rz0['share'] - er['past20'])))
    shown = {k: dict(平均=tab0[k]['π加重の平均の年率'], P15π=tab0[k]['P15π'], 最大下落=tab0[k]['最大下落']) for k in REF}
    ok_reg = all(v < 1e-9 for k in REF for v in reg[k].values()) and reg['実績の割合と_past20'] < 1e-9 \
        and abs(shown[K_BASE]['平均'] - 10.76) < 0.051 and abs(shown[K_NOW]['平均'] - 10.83) < 0.051 \
        and abs(shown[K_BASE]['P15π'] - 25.35) < 0.15 and abs(shown[K_NOW]['P15π'] - 26.75) < 0.15
    if not ok_reg:
        raise SystemExit(f'回帰の検査が通らない: {reg} {shown}')
    log('回帰の検査 ✓', shown)
    mdd_line = float(er['mdd'][2])
    base_P15 = float(er['P15'][0])

    # ── 形の範囲と条件 ──
    G = grid()
    ix = [P.index(c) for c in SIX]
    A = np.zeros((len(G), len(P)), dtype=np.float64)
    A[:, ix] = G
    e, c = fast.eval(A), cent.eval(A)
    with np.errstate(invalid='ignore'):
        meas = e['ok'] & c['ok']
        C1 = e['mdd'] >= mdd_line - EPS
        C2 = c['c30min'] >= 1.0 - EPS
        C3 = e['P15'] > base_P15 + EPS
    feas = meas & C1 & C2 & C3
    form = [{cc: int(v) * STEP for cc, v in zip(SIX, row) if v} for row in G]
    names = [name(f) for f in form]
    counts = dict(形の数=len(G), 測れない=int((~meas).sum()), C1で外れた=int((meas & ~C1).sum()),
                  C2で外れた=int((meas & C1 & ~C2).sum()), C3で外れた=int((meas & C1 & C2 & ~C3).sum()), 条件を通った=int(feas.sum()))
    log('条件', counts)

    def order(mask):
        ii = np.where(mask)[0].tolist()
        return sorted(ii, key=lambda i: (-round(float(e['mean_pi'][i]) / TIE), -float(e['P15'][i]), -float(e['mdd'][i]), names[i]))

    ch_jpy, _ = U.jpy_chains(chains)

    def final(ii):
        """目的の順に BATCH ずつ確かめ、最初に F1・F2 を通った形を返す"""
        seen = []
        for s in range(0, len(ii), BATCH):
            part = ii[s:s + BATCH]
            Fm = {K_BASE: BASEF, **{names[i]: form[i] for i in part}}
            assets = sorted({a for f in Fm.values() for a in f} | {'VOO'})
            k4, _ = N.chips_adj(rows, assets)
            with contextlib.redirect_stdout(io.StringIO()):
                vt = N.variants(Fm, rows, chains, k4)[UC.W_CRASH]
                tj = U.measure(Fm, rows, ch_jpy, mega=U.mega_map(rows, assets),
                               windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
            for i in part:
                nm = names[i]
                d = {N.VARS_JA[v]: round(100 * (vt[nm][v]['mean_pi'] - vt[K_BASE][v]['mean_pi']), 3) for v in N.VARS}
                f1 = all(vt[nm][v]['mean_pi'] > vt[K_BASE][v]['mean_pi'] + EPS for v in N.VARS)
                dj = 100 * (tj[nm]['_raw']['mean_pi'] - tj[K_BASE]['_raw']['mean_pi'])
                f2 = dj > 1e-10
                seen.append(dict(名前=nm, 平均=r(100 * e['mean_pi'][i]), P15π=r(100 * e['P15'][i]), 最大下落=r(100 * e['mdd'][i], 1),
                                 百年の最悪=r(c['c30min'][i], 3), 感度5本の私の案との差=d, F1=bool(f1), 円の平均の差=round(dj, 3), F2=bool(f2)))
                if f1 and f2:
                    return i, seen
            log('確かめ', s + len(part), '/', len(ii))
        return None, seen

    main_order = order(feas)
    ans_i, seen = final(main_order)
    nofbt = feas & (G[:, SIX.index('FBT')] == 0)
    alt_i, seen_alt = final(order(nofbt))

    # ── 詳しい物差し（答え・参照・目的の1位） ──
    DET = dict(REF)
    top_i = main_order[0] if main_order else None
    if ans_i is not None:
        DET['答え'] = form[ans_i]
    if top_i is not None and top_i != ans_i:
        DET['目的の1位（最終の確かめ前）'] = form[top_i]
    if alt_i is not None and alt_i != ans_i:
        DET['FBT を使わない答え'] = form[alt_i]
    Wd = W_of(DET.values())
    ed, cd, rzd = fast.eval(Wd), cent.eval(Wd), realized(Wd, fast)
    bd = br_all(Wd)
    assets = sorted({a for f in DET.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)
    with contextlib.redirect_stdout(io.StringIO()):
        tab = U.measure(dict(DET), rows, chains, mega=mega)[UC.W_CRASH]
        tj = U.measure(dict(DET), rows, ch_jpy, mega=mega, windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
    k4, _ = N.chips_adj(rows, assets)
    with contextlib.redirect_stdout(io.StringIO()):
        vtd = N.variants(dict(DET), rows, chains, k4)[UC.W_CRASH]
    _, sim = U.tables()
    pi, _, _ = E.load_pi()
    cc, seats, cpct = U.castle_copy()
    seats_used = list(seats)
    N.CASTLE_ARG = ','.join(f'{s}={CASTLE_PCT / len(seats_used):g}' for s in seats_used)
    N.NET_ARG['VBR'] = 'VBR'
    jb = list(DET).index(K_BASE)
    detail = {}
    for j, k in enumerate(DET):
        t = tab[k]
        q, pr_ = UC.upside(sim, t['_raw'], pi)
        try:
            # ★資産全体で渡す（ETF 側×0.9＋個別株10%）。2026-11-22 夜まで ETF 側100%＋個別株10%＝110%で渡していた（balance_check で発見）
            lk = N.lookthrough({c: v * (100 - CASTLE_PCT) / 100 for c, v in DET[k].items() if v})
        except Exception as ex:   # 参考だけ・読めなければ名指し
            lk = dict(読めず=str(ex)[:200])
        detail[k] = dict(
            形=DET[k], 名前=name(DET[k]), 全体の比=whole(DET[k]),
            元=dict(平均=t['π加重の平均の年率'], P15π=t['P15π'], P20_道の束=pr_.get('P20（道の束）'), P15π_A2を外す=t['P15π（A2を外す）'],
                   五パーセント未満=t['P5π（5%未満）'], 元本割れ=t['P0π（元本割れ）'], 最悪の世界=t['最悪の世界'], ぶれ=t['ぶれ'], 最大下落=t['最大下落'],
                   世界ごとの年率=t['世界ごとの年率'], 内部収益率の分位=q, 崩れ2000型_16から18年目=t['崩れ2000型_16〜18年目']),
            感度5本の私の案との差={N.VARS_JA[v]: round(100 * (vtd[k][v]['mean_pi'] - vtd[K_BASE][v]['mean_pi']), 3) for v in N.VARS},
            円=dict(平均=tj[k]['π加重の平均の年率'], P15π=tj[k]['P15π'], 最大下落=tj[k]['最大下落']),
            基礎率=dict(平均=r(100 * bd['主']['mean_pi'][j]), P15π=r(100 * bd['主']['P15'][j]), 五パーセント未満=r(100 * bd['主']['P5'][j]),
                     感度6本の私の案との差={v: r(100 * (bd[v]['mean_pi'][j] - bd[v]['mean_pi'][jb]), 3) for v in BR.VARS}),
            百年=dict(三十年の中央=r(cd['c30med'][j], 3), 三十年の最悪=r(cd['c30min'][j], 3)),
            実績=dict(年15パーセント以上の割合=r(100 * rzd['share'][j], 1), 年率の中央=r(100 * rzd['med'][j])),
            集中=dict(NVDA=lk.get('NVDA（資産全体）'), 半導体の連鎖=lk.get('半導体の連鎖（下限〜上限）'), 最大の1銘柄=lk.get('最大の1銘柄'),
                    城=f'{N.CASTLE_ARG}（席{len(seats_used)}社×{CASTLE_PCT / len(seats_used):g}%）'))

    by_ndx = {}
    for n in range(NDX_LO, NDX_HI + 1):
        ii = order(feas & (G[:, 0] == n))
        if ii:
            i = ii[0]
            by_ndx[f'NASDAQ100 {n * STEP}'] = dict(名前=names[i], 平均=r(100 * e['mean_pi'][i]), P15π=r(100 * e['P15'][i]),
                                                  最大下落=r(100 * e['mdd'][i], 1), 百年の最悪=r(c['c30min'][i], 3))
    top10 = [dict(名前=names[i], 平均=r(100 * e['mean_pi'][i]), P15π=r(100 * e['P15'][i]), 最大下落=r(100 * e['mdd'][i], 1),
                  百年の中央=r(c['c30med'][i], 3), 百年の最悪=r(c['c30min'][i], 3)) for i in main_order[:10]]
    out = dict(
        generated=time.strftime('%Y-%m-%d'), tool='night/ret_seek_check.py',
        kind='参考（測って選ぶだけ・形と選び方は道具の頭に固定し回す前にコミット）',
        question='NASDAQ100 40 / SMH 20 / ITA 15 / XLV 10 / VBR 15これからリターンを取りに行く構成に直して',
        reading='11-22 に私が選んだ守り寄りの形をもとに、期待のリターンを上げる形へ直す',
        regression=dict(差=reg, 表示=shown, 通過=ok_reg),
        lines=dict(C1_最大下落の線=r(100 * mdd_line, 2), C2_百年の最悪=1.0, C3_私の案のP15π=r(100 * base_P15, 2)),
        counts=counts,
        答え=(dict(名前=names[ans_i], 形=form[ans_i], 全体の比=whole(form[ans_i]), 確かめた順位=len(seen))
             if ans_i is not None else '決まりを満たす形は無い'),
        FBTを使わない答え=(dict(名前=names[alt_i], 形=form[alt_i], 全体の比=whole(form[alt_i]), 確かめた順位=len(seen_alt))
                       if alt_i is not None else '決まりを満たす形は無い'),
        目的の上位10=top10, 最終の確かめ=seen, 最終の確かめ_FBTなし=seen_alt, NASDAQ100の比ごとの目的の1位=by_ndx,
        詳しい物差し=detail,
        caveats=['未来の世界は予想・分散の上乗せは仮定', '実績は一つの時代（テックと半導体が勝った26年）',
                 '100年の写しの NASDAQ100 は業種を固定した代わり（年1回の入れ替えを数えない）',
                 'C1 の線・芯の縛り・条件・目的は私が決めた', '形どうしの差の多くは雑音に近い', '税と NISA の枠は物差しに入らない'],
        secs=round(time.time() - t0))
    with open(OUT, 'w') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    log('→', OUT, '答え', out['答え'] if isinstance(out['答え'], str) else out['答え']['名前'], f'{out["secs"]}s')


if __name__ == '__main__':
    main()
