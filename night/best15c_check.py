#!/usr/bin/env python3
"""night/best15c_check.py — 年率15%を狙いつつ、100年の代用も目的に入れて探し直す（best15c・2026-11-01・参考・配分は変えない）

ユーザー「探し直して」（直前の答え「100年の代用も目的に入れて探し直すこともできます」への返事）。
best15（docs/CLAUDE_ARCHIVE.md:20903）は100年の代用を「今より悪くしない」条件（⑧）にだけ使った。ここでは
15%以上の確率と100年の代用の両方を目的にする。門・採点・配分（portfolio.json）・注文書には触れない。
★候補・物差し・条件・選び方はこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする
  （`--selfcheck` は速い評価と標準の物差しの一致・写しの差し替えの一致だけを出し、探索の結果は出さない）。

今（portfolio.json の ETF 側・best15_check.check_now で照合）: NASDAQ100（物差しでは QQQM）50 / SMH 20 / ITA 20 / XLV 10
候補（18本）: 100年の写しがある本だけ（写しの無い本は目的の片方を測れない）
  核4本 QQQM・SMH・ITA・XLV ＋ FBT・GDX・XLU・XLP・XLE・XLF・XLI・XLY・VBR・VUG・VTV・IJR・XLK・VOO
  写しは best15_check と同じ（unx_assets.century_parts＋best15_check.century_extend）:
  QQQM＝French のテック3業種65%＋市場35%・SMH＝Chips・ITA＝Aero/Guns・XLV＝Drugs/MedEq/Hlth・FBT＝Drugs・GDX＝Gold・XLU＝Util・
  VOO＝市場・XLP/XLE/XLF/XLI/XLY＝49業種の時価加重・VBR＝SMALL HiBM・VUG＝BIG LoBM・VTV＝BIG HiBM・IJR＝SMALL の3つの平均・XLK＝テック3業種
  外した15本（金・銀・債券・米国外・国・MOAT ほか）は100年の写しが無い。best15 の第1段で T1 の最良を上回った本は FBT と XLK だけで、
  外した本は1本も上回っていない（out/best15_check.json の stage1）
形: ETF 側100%・5%刻み・7本まで・1本40%まで（best15 と同じ）
物差し（best15 と同じ）: unx_assets.measure の USD・崩れあり（2000-09〜2026-09）を行列で写した best15_check.Fast と、
  unx_assets.century_monthly を写した best15_check.Cent（`--selfcheck` で一致を確かめる）
  P15π＝20年の毎月の積立の内部収益率が年15%以上になる確率（5つの世界・π は out/bestpf_calibration.json）
  C＝100年の代用 30年の毎月の積立（起点1965〜1995・31窓）の市場との比の中央値
条件 T1c（どれも今を下回らない）: ⓪ P15π ≥ 今 ＋ best15 の T1 の8つ（① π加重の平均 ② 最悪の世界 ③ 5%未満 ④ 最大下落
  ⑤ A2を外した P15π ⑥ 未来の世界だけの P15π ⑦ 過去の転がる20年で15%以上 ⑧ 100年の代用の30年の中央と最悪）
選び方（釣り合い）: 条件を通った形の中で
  s＝min( (P15π−今)/(P15π の最大−今), (C−今)/(C の最大−今) )
  ＝「15%以上の確率と100年の倍率のそれぞれで、取れる改善のうち何割を取ったか」の小さいほう を最大にする
  （最大は同じ段の条件を通った形の中で取る。s を小数3桁に丸めて同じなら P15π → π加重の平均 → 最大下落が浅い → 名前の順）
探索:
  第0段＝核4本だけ／第1段＝核4本＋候補1本（候補は5%以上・核は0%も可）の総当たり → 第0段と第1段を合わせた最大で s を出し、候補ごとの最良の s
  第2段＝核4本＋第1段の s の上位5本（s>0 の本の中で。第1段で P15π の最良の本と C の最良の本が入っていなければ s の下位から入れ替える）の総当たり（7本まで）
最終の確かめ（第2段の s の上位30を順に・最初に通った形を答えにする）:
  F1 感度5本（主・A2を外す・半導体の基礎率・分散の上乗せなし・共分散を A2 の窓から＝ndx_swap_check.variants）すべてで P15π ≥ 今 ∧ π加重の平均 ≥ 今
  F2 円・崩れあり の枠で π加重の平均 ≥ 今 ∧ 最大下落 ≥ 今
  F3 100年の代用を (a) 各本の費用（経費率＋NISA で戻らない配当の税）を引いた写し（相手の市場からは VOO の費用を引く）
     (b) FBT の写しを XLV と同じ（医薬品・医療機器・医療サービスの時価加重）にした写し の両方で、30年の中央と最悪が今以上
  通る形が無ければ「今のまま」
併せて出す（判定に使わない）: 両端（条件を通った形の中の P15π の最大・C の最大）／境界（P15π の0.5pt刻みごとの C の最大）／
  感度 C1（FBT の写しを XLV と同じにして第2段を選び直す）・C2（費用を引いた写しで選び直す）の答え（最終の確かめは掛けない）／
  参考の形（今・best15 の決まりの答え・best15 の勧め② SMH40/FBT30/ITA15/NASDAQ100 15・both_balance の1位 SMH30/ITA45/FBT25・
  century_best の釣り合い SMH15/ITA35/FBT50）を同じ物差しで／答えの形の詳しい物差し（20年の積立の100年の代用・円の枠・中身の集中）
⚠ 限界: 100年の写しは後から勝ちが分かった業種を含む（医薬品・防衛）・FBT の写しは大型の製薬でバイオのぶれ（24%対19.5%）を写さない
  （F3(b) と C1 で確かめる）・写しの無い本は候補に入らない・s の正規化は同じ段の最大に頼る・第1段は1本ずつの効き目で絞る・
  歴史の世界は2000年以降のテックの時代・未来の世界も予想・分散の上乗せは仮定・税は物差しに入らない・縛り（40%・7本・5%）は私が決めた
使い方: python3 night/best15c_check.py --selfcheck   （一致の確かめだけ）
        python3 night/best15c_check.py               → out/best15c_check.json
"""
import json, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'best15c_check.json')

import best15_check as B  # noqa: E402

CORE = list(B.CORE)
CANDS = ['FBT', 'GDX', 'XLU', 'XLP', 'XLE', 'XLF', 'XLI', 'XLY', 'VBR', 'VUG', 'VTV', 'IJR', 'XLK', 'VOO']
POOL = CORE + CANDS
NEXTRA, SDEC, NFIN, EPS = 5, 3, 30, 1e-12
REFS = {'best15 の決まりの答え SMH40/FBT25/NASDAQ100 15/GDX10/ITA5/XLK5': {'SMH': 40, 'FBT': 25, 'QQQM': 15, 'GDX': 10, 'ITA': 5, 'XLK': 5},
        'best15 の勧め② SMH40/FBT30/ITA15/NASDAQ100 15': {'SMH': 40, 'FBT': 30, 'ITA': 15, 'QQQM': 15},
        'both_balance の1位 SMH30/ITA45/FBT25': {'SMH': 30, 'ITA': 45, 'FBT': 25},
        'century_best の釣り合い SMH15/ITA35/FBT50': {'SMH': 15, 'ITA': 35, 'FBT': 50}}


def log(*a):
    print('[best15c]', *a, flush=True)


class CentP:
    """best15_check.Cent と同じ式で、写し（parts）と相手の市場（mkt）を差し替える"""

    def __init__(self, U, pool, parts, mkt=None):
        C = U.century_parts()
        F, mkt0, endm = C['F'], C['mkt'], C['endm']
        mkt = mkt0 if mkt is None else mkt
        wins = [(y, F.months((y + 1) * 100 + 1, 360)) for y in range(1965, 1996)]
        wins = [(y, w) for y, w in wins if w[-1] <= endm]
        hi = max(w[-1] for _, w in wins)
        ms = [m for m in sorted(mkt0) if 196601 <= m <= hi]
        self.pool = list(pool)
        self.has = np.array([c in U.MONTHLY_OK and c in parts for c in pool])
        Pm = np.zeros((len(pool), len(ms)))
        for i, c in enumerate(pool):
            if self.has[i]:
                miss = [m for m in ms if m not in parts[c]]
                if miss:
                    raise SystemExit(f'差し替えた写し {c} に欠けた月がある（{miss[:3]}…）')
                Pm[i] = [parts[c][m] for m in ms]
        self.Pm = Pm
        idx = {m: i for i, m in enumerate(ms)}
        self.win = [(y, idx[w[0]], idx[w[-1]]) for y, w in wins]
        mk = np.array([mkt[m] for m in ms])
        self.mk = np.array([B.Cent._dca(mk[None, :], a, b)[0] for _, a, b in self.win])

    _dca = staticmethod(B.Cent._dca)
    eval = B.Cent.eval


def cent_chunked(ct, A, chunk=20000):
    med, mn, ok = np.full(len(A), np.nan), np.full(len(A), np.nan), np.zeros(len(A), bool)
    for s in range(0, len(A), chunk):
        e = ct.eval(A[s:s + chunk].astype(np.float64))
        med[s:s + chunk], mn[s:s + chunk], ok[s:s + chunk] = e['c30med'], e['c30min'], e['ok']
    return dict(c30med=med, c30min=mn, ok=ok)


def feas(E, now, ce=None, nowc=None):
    """T1c の条件（⓪＋best15 の T1 の8つ）。ce・nowc を渡すと⑧を差し替えた写しで裁く"""
    ce = ce if ce is not None else dict(ok=E['cok'], c30med=E['c30med'], c30min=E['c30min'])
    nw = dict(now) if nowc is None else dict(now, c30med=nowc['c30med'], c30min=nowc['c30min'])
    with np.errstate(invalid='ignore'):
        g = B.gates(E, ce, nw, 'T1')
        g['⓪15%以上'] = E['P15'] >= now['P15'] - EPS
        return B.feasible(g, E['ok']), g


def maxima(E, f, cmed):
    if not f.any():
        return None
    return dict(P15=float(np.max(E['P15'][f])), C=float(np.max(cmed[f])))


def score(E, now, mx, cmed, cnow):
    dp, dc = mx['P15'] - now['P15'], mx['C'] - cnow
    if dp <= EPS or dc <= EPS:
        raise SystemExit(f'改善の余地が無い（P15π の幅 {dp}・C の幅 {dc}）＝釣り合いの式が使えない')
    a = (E['P15'] - now['P15']) / dp
    b = (cmed - cnow) / dc
    return np.minimum(a, b), a, b


def order_s(idx, E, s, A, k=5000):
    idx = np.asarray(idx)
    if len(idx) > k:
        idx = idx[np.argsort(-s[idx], kind='stable')[:k]]
    return sorted(idx.tolist(), key=lambda i: (-round(float(s[i]), SDEC), -E['P15'][i], -E['mean_pi'][i], -E['mdd'][i], B.name_of(A[i], POOL)))


def form_of(row):
    return {POOL[j]: int(row[j]) * B.STEP for j in range(len(POOL)) if row[j] > 0}


def brief(E, i, s=None, a=None, b=None, cmed=None, cmin=None):
    d = dict(P15π=round(100 * E['P15'][i], 2), 平均=round(100 * E['mean_pi'][i], 2), 最悪の世界=round(100 * E['worst'][i], 2),
             五パーセント未満=round(100 * E['P5'][i], 2), 最大下落=round(100 * E['mdd'][i], 1), 過去の20年=round(100 * E['past20'][i], 1),
             百年の中央=round(float((cmed if cmed is not None else E['c30med'])[i]), 3),
             百年の最悪=round(float((cmin if cmin is not None else E['c30min'])[i]), 3))
    if s is not None:
        d.update(s=round(float(s[i]), 4), P15の取り分=round(float(a[i]), 3), 百年の取り分=round(float(b[i]), 3))
    return d


def main():
    t0 = time.time()
    B.check_now()
    import unx_assets as U
    import ndx_swap_check as N
    import upside_check as UC
    import bestpf_check as BC
    res = U.build()
    rows, chains = res['rows'], res['chains']
    miss = [c for c in POOL if c not in rows]
    if miss:
        raise SystemExit(f'行が無い: {miss}')
    C = B.century_extend(U)
    fast, cent = B.Fast(U, rows, chains, POOL), B.Cent(U, POOL)
    if not cent.has.all():
        raise SystemExit(f'100年の写しが無い本: {[c for c, h in zip(POOL, cent.has) if not h]}')
    parts = C['parts']
    fee = {c: rows[c]['er_vehicle'] + rows[c]['tax_drag'] for c in POOL}
    parts_c1 = dict(parts)
    parts_c1['FBT'] = parts['XLV']
    parts_c2 = {c: {m: r - fee[c] / 12 for m, r in parts[c].items()} for c in POOL}
    mkt_c2 = {m: r - fee['VOO'] / 12 for m, r in C['mkt'].items()}
    cent0, cent1, cent2 = CentP(U, POOL, parts), CentP(U, POOL, parts_c1), CentP(U, POOL, parts_c2, mkt_c2)

    # 自己検問: 速い評価＝標準の物差し・差し替えなしの CentP＝Cent
    sc = B.selfcheck(U, rows, chains, POOL, fast, cent)
    rng = np.random.default_rng(5)
    Wr = rng.integers(0, 9, size=(400, len(POOL))).astype(np.float64)
    Wr[Wr.sum(axis=1) == 0, 0] = 1
    d0 = max(float(np.nanmax(np.abs(cent0.eval(Wr)[k] - cent.eval(Wr)[k]))) for k in ('c30med', 'c30min'))
    sc['差し替えなしの CentP と Cent の最大の差'] = d0
    sc['一致'] = bool(sc['一致'] and d0 < 1e-12)
    log('自己検問', json.dumps(sc, ensure_ascii=False, default=str))
    if not sc['一致']:
        raise SystemExit('速い評価が標準の物差しと一致しない')
    if '--selfcheck' in sys.argv:
        return

    n = len(POOL)
    W0 = np.array([[B.NOW.get(c, 0) for c in POOL]], dtype=np.float64)
    e0, c0 = fast.eval(W0), cent.eval(W0)
    now = {k: float(v[0]) for k, v in {**e0, **c0}.items() if k != 'ok'}
    now1 = {k: float(v[0]) for k, v in cent1.eval(W0).items() if k != 'ok'}
    now2 = {k: float(v[0]) for k, v in cent2.eval(W0).items() if k != 'ok'}
    log('今', {k: round(v, 4) for k, v in now.items()}, '費用を引いた100年', now2, 'FBT の写しを XLV と同じに', now1)

    # ── 第0段・第1段 ──
    idx_core = [POOL.index(c) for c in CORE]
    A4 = B.all_forms(4, 4, B.CAP)
    A0 = np.zeros((len(A4), n), dtype=np.int8)
    A0[:, idx_core] = A4
    blocks = [('核4本だけ', A0)]
    A5 = B.all_forms(5, 5, B.CAP, must=4)
    for x in CANDS:
        A = np.zeros((len(A5), n), dtype=np.int8)
        A[:, idx_core + [POOL.index(x)]] = A5
        blocks.append((x, A))
    A01 = np.vstack([b for _, b in blocks])
    lab = np.concatenate([np.full(len(b), nm, dtype=object) for nm, b in blocks])
    E01 = B.run_forms(fast, cent, A01, now)
    f01, _ = feas(E01, now)
    mx1 = maxima(E01, f01, E01['c30med'])
    s01, a01, b01 = score(E01, now, mx1, E01['c30med'], now['c30med'])
    st1 = {}
    for nm, _ in blocks:
        ii = np.where(f01 & (lab == nm))[0]
        if not len(ii):
            st1[nm] = None
            continue
        b = order_s(ii, E01, s01, A01)[0]
        st1[nm] = dict(最良の形=B.name_of(A01[b], POOL), **brief(E01, b, s01, a01, b01), 通った形=int(len(ii)),
                       P15πの最良=round(100 * float(E01['P15'][ii].max()), 2), 百年の中央の最良=round(float(E01['c30med'][ii].max()), 3),
                       _s=float(s01[b]), _p=float(E01['P15'][ii].max()), _c=float(E01['c30med'][ii].max()))
        log('第1段', nm, json.dumps({k: v for k, v in st1[nm].items() if not k.startswith('_')}, ensure_ascii=False))
    elig = [x for x in CANDS if st1[x] and st1[x]['_s'] > 0]
    extras = sorted(elig, key=lambda x: (-st1[x]['_s'], x))[:NEXTRA]
    have = [x for x in CANDS if st1[x]]
    bestP = max(have, key=lambda x: (st1[x]['_p'], x)) if have else None
    bestC = max(have, key=lambda x: (st1[x]['_c'], x)) if have else None
    forced = []
    for need in (bestP, bestC):
        if need is None or need in extras:
            continue
        if len(extras) < NEXTRA:
            extras.append(need)
        else:
            j = max(k for k, x in enumerate(extras) if x not in forced)
            extras[j] = need
        forced.append(need)
    assets2 = CORE + extras
    log('第1段の最大', mx1, '第2段の本', assets2, '（P15π の最良', bestP, '・C の最良', bestC, '）')

    # ── 第2段 ──
    A2s = B.all_forms(len(assets2), B.KMAX, B.CAP)
    A2 = np.zeros((len(A2s), n), dtype=np.int8)
    A2[:, [POOL.index(c) for c in assets2]] = A2s
    log('第2段の形', len(A2))
    E2 = B.run_forms(fast, cent, A2, now)
    f2, g2 = feas(E2, now)
    cnt = {k: int(np.nansum(v & E2['ok'])) for k, v in g2.items()}
    log('第2段で条件を通った形', int(f2.sum()), '条件ごと', cnt)
    if not f2.any():
        raise SystemExit('第2段で条件を通った形が無い')
    mx2 = maxima(E2, f2, E2['c30med'])
    s2, a2, b2 = score(E2, now, mx2, E2['c30med'], now['c30med'])
    ii = np.where(f2)[0]
    top = order_s(ii, E2, s2, A2)[:NFIN]
    forms = {B.name_of(A2[i], POOL): form_of(A2[i]) for i in top}

    # ── 最終の確かめ ──
    ch_jpy, _ = U.jpy_chains(chains)
    fc, _, _ = B.final_check(U, N, rows, chains, ch_jpy, forms, 'T1')
    Wt = np.array([[f.get(c, 0) for c in POOL] for f in forms.values()], dtype=np.float64)
    k1, k2 = cent1.eval(Wt), cent2.eval(Wt)
    finals, answer = [], None
    for j, (nm, i) in enumerate(zip(forms, top)):
        f3a = bool(k2['c30med'][j] >= now2['c30med'] - EPS and k2['c30min'][j] >= now2['c30min'] - EPS)
        f3b = bool(k1['c30med'][j] >= now1['c30med'] - EPS and k1['c30min'][j] >= now1['c30min'] - EPS)
        ok = bool(fc[nm]['F1の合否'] and fc[nm]['F2の合否'] and f3a and f3b)
        finals.append(dict(名前=nm, **brief(E2, i, s2, a2, b2), F1=fc[nm]['F1の合否'], F2=fc[nm]['F2の合否'], F3a費用=f3a, F3bFBTの写し=f3b,
                           費用を引いた百年=[round(float(k2['c30med'][j]), 3), round(float(k2['c30min'][j]), 3)],
                           FBTの写しをXLVと同じにした百年=[round(float(k1['c30med'][j]), 3), round(float(k1['c30min'][j]), 3)],
                           感度ごとの差=fc[nm]['感度ごとの差'], 円の枠=fc[nm]['円の枠']))
        if ok and answer is None:
            answer = nm
    log('答え', answer)

    # ── 両端と境界 ──
    iP = order_s(ii, E2, E2['P15'], A2)[0]          # P15π の最大（同じなら平均→最大下落→名前）
    iC = order_s(ii, E2, E2['c30med'], A2)[0]       # 100年の中央の最大
    ends = {'15%以上の確率の最大': dict(名前=B.name_of(A2[iP], POOL), **brief(E2, iP, s2, a2, b2)),
            '100年の中央の最大': dict(名前=B.name_of(A2[iC], POOL), **brief(E2, iC, s2, a2, b2))}
    front = []
    t = now['P15']
    while t <= mx2['P15'] + EPS:
        jj = ii[E2['P15'][ii] >= t - EPS]
        if len(jj):
            b = order_s(jj, E2, E2['c30med'], A2)[0]
            front.append(dict(P15πの下限=round(100 * t, 2), 名前=B.name_of(A2[b], POOL), **brief(E2, b)))
        t += 0.005

    # ── 感度 C1・C2（第2段を選び直す・最終の確かめは掛けない）──
    pre = np.where(E2['cok'])[0]
    sens = {}
    for key, ct, nowc, lab_ in (('C1', cent1, now1, 'FBT の写しを XLV と同じにして選び直す'), ('C2', cent2, now2, '費用を引いた100年の写しで選び直す')):
        alt = dict(c30med=np.full(len(A2), np.nan), c30min=np.full(len(A2), np.nan), ok=np.zeros(len(A2), bool))
        ce = cent_chunked(ct, A2[pre])
        for k in alt:
            alt[k][pre] = ce[k]
        fa, _ = feas(E2, now, ce=alt, nowc=nowc)
        if not fa.any():
            sens[key] = dict(説明=lab_, 答え=None)
            continue
        mxa = maxima(E2, fa, alt['c30med'])
        sa, aa, ba = score(E2, now, mxa, alt['c30med'], nowc['c30med'])
        ia = order_s(np.where(fa)[0], E2, sa, A2)[0]
        sens[key] = dict(説明=lab_, 答え=B.name_of(A2[ia], POOL), **brief(E2, ia, sa, aa, ba, alt['c30med'], alt['c30min']),
                         通った形=int(fa.sum()), 最大=dict(P15π=round(100 * mxa['P15'], 2), 百年の中央=round(mxa['C'], 3)), _i=int(ia))
        log('感度', key, sens[key]['答え'])

    # ── 詳しい物差し（今・答え・両端・感度の答え・参考の形）──
    show_forms = {'今': dict(B.NOW)}
    if answer:
        show_forms['答え'] = forms[answer]
    show_forms['15%以上の確率の最大'] = form_of(A2[iP])
    show_forms['100年の中央の最大'] = form_of(A2[iC])
    for key in ('C1', 'C2'):
        if sens.get(key, {}).get('答え'):
            show_forms[f'感度{key}の答え'] = form_of(A2[sens[key]['_i']])
    show_forms.update(REFS)
    assets = sorted({a for f in show_forms.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)
    tab = U.measure(show_forms, rows, chains, mega=mega)
    tjs = U.measure(show_forms, rows, ch_jpy, mega=mega, windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
    Ws = np.array([[f.get(c, 0) for c in POOL] for f in show_forms.values()], dtype=np.float64)
    q1, q2 = cent1.eval(Ws), cent2.eval(Ws)
    detail = {}
    for j, (nm, f) in enumerate(show_forms.items()):
        cm = U.century_monthly(f)
        detail[nm] = dict(形=f, 主=B.show(tab[UC.W_CRASH][nm], None if cm is None else U.strip_century(cm)),
                          ドットコム級なし=B.show(tab[UC.W_DC][nm]),
                          円の枠={k: tjs[nm][k] for k in ('π加重の平均の年率', 'P15π', 'P5π（5%未満）', '最大下落', '過去の転がる20年で15%以上')},
                          百年_費用を引く=[round(float(q2['c30med'][j]), 3), round(float(q2['c30min'][j]), 3)],
                          百年_FBTの写しをXLVと同じ=[round(float(q1['c30med'][j]), 3), round(float(q1['c30min'][j]), 3)],
                          中身の集中=B.lookthrough(f))

    doc = dict(generated=time.strftime('%Y-%m-%d'), tool='night/best15c_check.py', kind='参考（配分は変えない・選び方は道具の頭に固定）',
               question='年率15%を狙いつつ、100年の代用も目的に入れて探し直す（best15 の続き）', pi=fast.pi, pool=POOL, now=B.NOW,
               now_raw=now, 今の100年_費用を引く=now2, 今の100年_FBTの写しをXLVと同じ=now1, selfcheck=sc,
               stage1={k: ({kk: vv for kk, vv in v.items() if not kk.startswith('_')} if v else None) for k, v in st1.items()},
               stage1_max=dict(P15π=round(100 * mx1['P15'], 2), 百年の中央=round(mx1['C'], 3)),
               stage2=dict(本=assets2, 形の数=int(len(A2)), 条件を通った形=int(f2.sum()), 条件ごと=cnt,
                           最大=dict(P15π=round(100 * mx2['P15'], 2), 百年の中央=round(mx2['C'], 3))),
               answer=answer or '今のまま', finals=finals, ends=ends, frontier=front,
               sensitivity={k: {kk: vv for kk, vv in v.items() if not kk.startswith('_')} for k, v in sens.items()}, detail=detail,
               secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    log('完了', doc['secs'], '秒', answer)


if __name__ == '__main__':
    main()
