#!/usr/bin/env python3
"""night/moat_track_test.py — 堀の検定②: のれん・無形を除いた ROIC で柱を測り直す（A）／機械で測れる実績の部品（B）（2026-10-11新設・読むだけ）

事前登録 out/moat_track_prereg.json のとおりに一度だけ裁く。門の採点・刻み・重み・関門・売却規律には触れない（絶対のルール1）。
決断待ち moat_redesign_1011 の②。①（night/moat_persist_test.py・合格0本）の続き。

A（柱の測り直し）: 歴史の読解（2013・2015）の irr・rep・dur・moatW（・dom）を、のれん・無形を除いた ROIC（門の roic の分母）の
  前方 +6〜+10年の驚きで裁く。同じ社・同じ表でのれん込みの ROIC の驚きも並べる（① の不合格が のれん＝買収のせいかを切り分ける）。
B（機械の実績の部品）: 全上場（USD・10-K・入口の売上2億ドル以上・金融と不動産を除く）で、
  M1 資本コストを上回った年の割合／M2 不況の年の営業利益の落ち込み／M3 粗利率の水準／M4 粗利率の下落幅／M5 シェアの趨勢 を
  同じ驚きで裁く（社単位＝各社は最新のビンテージで1回・4つのビンテージ 2012〜2015 で符号がそろうこと）。
驚き＝入口の順位から前方の順位を線形回帰した残差（retro_surprise.split）。順位の割合（0〜1）にして使う。
材料: out/_moat2_panel.json（night/moat_track_panel.py が companyfacts.zip から作る）・柱は moat_persist_test.load()・業種は out/sic_by_cik.json
出力: out/moat_track.json   使い方: python3 night/moat_track_test.py --count（数だけ・相関は測らない）／ 引数なし（本番・一度だけ）
"""
import datetime, json, math, os, statistics as S, sys

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import retro_surprise as RS        # noqa: E402  split（驚き）
import moat_persist_test as MP     # noqa: E402  load（柱・moat5・今日の堀指数）・pooled・perm・holm・spear・partial・grade_table
import moat_track_panel as MTP     # noqa: E402  read_ciks・selfcheck（backtest_core との一致）
import industry_trends as IT       # noqa: E402  sic_map（SEC submissions の SIC・out/sic_by_cik.json に貯める）

OUT = os.path.join(BASE, 'out')
PANEL = os.path.join(OUT, '_moat2_panel.json')
PRE = os.path.join(OUT, 'moat_track_prereg.json')
VINT = (2012, 2013, 2014, 2015)
READ_V = (2013, 2015)
NPERM = 2000
SEED_A, SEED_B = 20261012, 20261013
MIN_REV = 200e6
HURDLE = 0.09                       # M1 の資本コストの目安（retro_kills3 の固定 WACC 9% と同じ）
FLOOR = 0.10                        # B の主の判定の効果の下限（社単位の ρ）
MIN_N_B, MIN_N_A, MIN_N_VINT, MODE_CAP = 250, 150, 100, 0.85   # B の下限250（M2 が社単位で297社＝数を見て決めた・相関は見ていない）
SEMI_SIC = {'3674', '3559', '3825', '3827'}   # 頑健さ: 半導体と装置・検査に近い SIC を除く
PILLARS = ['irr', 'rep', 'dur', 'moatW', 'dom']
REFS_A = ['moat5', 'moat_today', 'irr_today']
COMPS = ['M1', 'M2', 'M3', 'M4', 'M5']            # 主（向きはどれも「高いほど持続」＝+）
REFS_B = ['R1', 'R2', 'R3', 'R4']                 # 参考（判定に使わない）
DESC = {
    'M1': '資本コストを上回った年の割合（入口5年でのれん・無形を除く ROIC≥9% の年÷測れた年・4年以上）',
    'M2': '不況の年の営業利益の落ち込み＝min(営業利益 2009・2010)÷max(2007・2008)−1（門の p2 と同じ量・高いほど浅い）',
    'M3': '粗利率の水準（入口5年の中央値・3年以上）',
    'M4': '粗利率の下落幅＝入口の年の粗利率 − その前4年の最高（2年以上）・高いほど下がっていない',
    'M5': 'シェアの趨勢＝((1+自社の売上の伸び)÷(1+同業の中央値))^4−1（4年・同業は SIC3 で5社以上、無ければ SIC2 で5社以上）',
    'R1': 'ROIC の安定（のれん・無形を除く ROIC の変動係数の符号を反転・平均>0・4年以上＝門の p1 と同じ量）',
    'R2': '営業利益率の安定（変動係数の符号を反転・平均>0・4年以上）',
    'R3': '売上の伸び（4年の年率・向きは決めない）',
    'R4': '不況の年の営業利益率の落ち込み＝min(2009・2010)−max(2007・2008)（pt）',
}
OUTC = {'O1t': ('e_rt', 'f_rt2', '前方 +6〜+10年の のれん・無形を除く ROIC の驚き（錨 入口5年の中央値）'),
        'O1g': ('e_rg', 'f_rg2', '前方 +6〜+10年の のれん込み ROIC の驚き（錨 入口5年の中央値）'),
        'O2m': ('e_opm', 'f_opm2', '前方 +6〜+10年の営業利益率の中央値の驚き（錨 入口5年の中央値）'),
        'O3t': ('e_rt', 'f_rt1', '前方 +1〜+5年の のれん・無形を除く ROIC の驚き（錨 入口5年の中央値）')}
I_REV, I_OP, I_GM, I_OPM, I_RG, I_RT = range(6)


# ── 材料から入口・前方・部品を作る ──
def win(rows, ys, idx, need):
    v = [(rows.get(str(y)) or [None] * 6)[idx] for y in ys]
    v = [x for x in v if x is not None]
    return v if len(v) >= need else None


def med(v):
    return None if v is None else S.median(v)


def cv_neg(v):
    if v is None:
        return None
    m = sum(v) / len(v)
    return None if m <= 0 else -S.pstdev(v) / m


def g4(P, Y):
    r0, r1 = (P.get(str(Y - 4)) or [None])[0], (P.get(str(Y)) or [None])[0]
    return None if (r0 is None or r1 is None or r0 <= 0 or r1 <= 0) else (r1 / r0) ** 0.25 - 1


def firm_vintage(f, Y):
    """1社・1ビンテージの入口（その時点で読めた数字）・前方（今日の数字）・部品"""
    P, L = f['pit'].get(str(Y)) or {}, f['latest']
    ent = range(Y - 4, Y + 1)
    d = {'rev': (P.get(str(Y)) or [None])[0]}
    rt, rg, om = win(P, ent, I_RT, 4), win(P, ent, I_RG, 4), win(P, ent, I_OPM, 4)
    d.update(e_rt=med(rt), e_rg=med(rg), e_opm=med(om))
    a2, a1 = range(Y + 6, Y + 11), range(Y + 1, Y + 6)
    d.update(f_rt2=med(win(L, a2, I_RT, 3)), f_rg2=med(win(L, a2, I_RG, 3)),
             f_opm2=med(win(L, a2, I_OPM, 3)), f_rt1=med(win(L, a1, I_RT, 3)))
    # 部品（その時点で読めた数字だけ）
    d['M1'] = None if rt is None else sum(1 for x in rt if x >= HURDLE) / len(rt)
    op = {y: (P.get(str(y)) or [None] * 6)[I_OP] for y in (2007, 2008, 2009, 2010)}
    pk = [op[y] for y in (2007, 2008) if op[y] is not None]
    tr = [op[y] for y in (2009, 2010) if op[y] is not None]
    d['M2'] = (min(tr) / max(pk) - 1) if (pk and tr and max(pk) > 0) else None
    gm = win(P, ent, I_GM, 3)
    d['M3'] = med(gm)
    gmY = (P.get(str(Y)) or [None] * 6)[I_GM]
    prior = win(P, range(Y - 4, Y), I_GM, 2)
    d['M4'] = None if (gmY is None or prior is None) else gmY - max(prior)
    d['g4'] = g4(P, Y)
    d['R1'], d['R2'], d['R3'] = cv_neg(rt), cv_neg(om), d['g4']
    om4 = {y: (P.get(str(y)) or [None] * 6)[I_OPM] for y in (2007, 2008, 2009, 2010)}
    pk2 = [om4[y] for y in (2007, 2008) if om4[y] is not None]
    tr2 = [om4[y] for y in (2009, 2010) if om4[y] is not None]
    d['R4'] = (min(tr2) - max(pk2)) if (pk2 and tr2) else None
    return d


def share_trend(V, sic):
    """M5: 同じビンテージの母集団（入口の売上2億ドル以上・金融と不動産を除く・伸びが測れる社）の同業中央値に対する4年のシェアの変化"""
    g3, g2 = {}, {}
    for c, d in V.items():
        s = sic.get(c) or ''
        if d['g4'] is None or len(s) < 3:
            continue
        g3.setdefault(s[:3], []).append(d['g4'])
        g2.setdefault(s[:2], []).append(d['g4'])
    for c, d in V.items():
        s = sic.get(c) or ''
        gi, gm = d['g4'], None
        if gi is not None and len(s) >= 3:
            if len(g3.get(s[:3], [])) >= 5:
                gm = S.median(g3[s[:3]])
            elif len(g2.get(s[:2], [])) >= 5:
                gm = S.median(g2[s[:2]])
        d['M5'] = None if gm is None else ((1 + gi) / (1 + gm)) ** 4 - 1


def in_universe(d, s):
    return (d['rev'] is not None and d['rev'] >= MIN_REV and s and len(s) >= 2 and not s.startswith('6'))


# ── 統計（numpy・B 用。A は moat_persist_test と同じ道具をそのまま使う） ──
def rankavg(a):
    a = np.asarray(a, dtype=float)
    _u, inv, cnt = np.unique(a, return_inverse=True, return_counts=True)
    cum = np.cumsum(cnt)
    return ((cum - cnt + 1 + cum) / 2.0)[inv]


def rho_p(x, y, seed, strata=None):
    """Spearman ρ と置換の p（両側・hit/NPERM＝moat_persist_test.perm と同じ数え方）。strata があればその中で入れ替える"""
    if len(x) < 20:
        return None, None
    rx, ry = rankavg(x), rankavg(y)
    rx = (rx - rx.mean()) / (rx.std() or 1)
    ry = (ry - ry.mean()) / (ry.std() or 1)
    n = len(rx)
    obs = float(rx @ ry / n)
    rng = np.random.default_rng(seed)
    groups = None
    if strata is not None:
        st = np.asarray(strata)
        groups = [np.where(st == s)[0] for s in np.unique(st)]
    hit = 0
    yy = ry.copy()
    for _ in range(NPERM):
        if groups is None:
            yy = rng.permutation(ry)
        else:
            for g in groups:
                yy[g] = rng.permutation(ry[g])
        # 入れ替えても平均・分散は同じなので内積÷n がそのまま相関
        if abs(float(rx @ yy / n)) >= abs(obs) - 1e-12:
            hit += 1
    return obs, hit / NPERM


def pct_of(V, keys, e, f):
    """母集団 keys の中で驚きを作り、順位の割合（0〜1）"""
    tk = [k for k in keys if V[k][e] is not None and V[k][f] is not None]
    if len(tk) < 20:
        return {}, len(tk), None
    _fit, res, r2 = RS.split([V[k][e] for k in tk], [V[k][f] for k in tk])
    rk = MP.ranks(res)
    return {k: rk[i] / len(tk) for i, k in enumerate(tk)}, len(tk), (None if r2 is None else round(r2, 3))


def within(pct, grp, minsize=5):
    g = {}
    for k in pct:
        s = grp.get(k)
        if s:
            g.setdefault(s, []).append(k)
    out = {}
    for s, ks in g.items():
        if len(ks) < minsize:
            continue
        rk = MP.ranks([pct[k] for k in ks])
        for i, k in enumerate(ks):
            out[k] = rk[i] / len(ks)
    return out


def r3(v):
    return None if v is None else round(v, 3)


def pooled_B(V, P, k, o='O1t'):
    """B の社単位: 各社は目的変数 o の母集団に入った最新のビンテージで1回だけ（その年に部品が無ければ数えない＝①の pooled と同じ）"""
    a, b, st, seen = [], [], [], set()
    for y in (2015, 2014, 2013, 2012):
        pct = P[y][o]
        for c in pct:
            if c in seen:
                continue
            seen.add(c)
            v = V[y][c].get(k)
            if v is None:
                continue
            a.append(v); b.append(pct[c]); st.append(y)
    return a, b, st


# ── 本体 ──
def build(fetch_sic=True):
    pan = json.load(open(PANEL))
    F = pan['firms']
    V = {y: {} for y in VINT}
    for c, f in F.items():
        for y in VINT:
            if str(y) in f['pit']:
                V[y][c] = firm_vintage(f, y)
    need = sorted({int(c) for y in VINT for c, d in V[y].items() if d['rev'] is not None and d['rev'] >= MIN_REV})
    sic = {str(k): v for k, v in IT.sic_map(need, fetch=fetch_sic).items()}
    for y in VINT:
        U = {c: d for c, d in V[y].items() if in_universe(d, sic.get(c))}
        share_trend(U, sic)
        for c, d in V[y].items():
            d.setdefault('M5', None)
    return pan, V, sic


def universes(V, sic):
    """B の母集団: ビンテージごと・目的変数ごとの社（入口の売上2億ドル以上・SIC あり・金融と不動産を除く・入口と前方がそろう）"""
    U = {}
    for y in VINT:
        base = [c for c, d in V[y].items() if in_universe(d, sic.get(c))]
        U[y] = {o: [c for c in base if V[y][c][e] is not None and V[y][c][f] is not None] for o, (e, f, _) in OUTC.items()}
        U[y]['_base'] = base
    return U


def read_sets(V):
    """A の材料: 読解の社（ビンテージごと）の柱（moat_persist_test.load）と、この表の入口・前方"""
    D = MP.load()
    _keep, t2c = MTP.read_ciks()
    R = {}
    for y in READ_V:
        R[y] = {}
        for t, p in D[y].items():
            c = str(t2c.get(t))
            v = V[y].get(c)
            if v is None:
                continue
            R[y][t] = dict(p, **{k: v[k] for k in ('e_rt', 'e_rg', 'e_opm', 'f_rt2', 'f_rg2', 'f_opm2', 'f_rt1', 'rev')},
                           **{k: v.get(k) for k in COMPS + REFS_B}, cik=c)
    return D, R


def counts(V, sic, U, R):
    out = {'B': {}, 'A': {}}
    for y in VINT:
        b = {o: len(U[y][o]) for o in OUTC}
        b['母集団（売上2億ドル以上・SIC あり・金融と不動産を除く）'] = len(U[y]['_base'])
        b['部品の被覆（O1t の母集団の中）'] = {k: sum(1 for c in U[y]['O1t'] if V[y][c].get(k) is not None) for k in COMPS + REFS_B}
        out['B'][str(y)] = b
    for y in READ_V:
        both = [t for t, d in R[y].items() if None not in (d['e_rt'], d['f_rt2'], d['e_rg'], d['f_rg2'])]
        out['A'][str(y)] = {'読解の社（表にある）': len(R[y]), 'O1t と O1g がそろう': len(both),
                            'O2m': sum(1 for d in R[y].values() if d['e_opm'] is not None and d['f_opm2'] is not None),
                            'O3t': sum(1 for d in R[y].values() if d['e_rt'] is not None and d['f_rt1'] is not None),
                            '柱（O1t と O1g がそろう社の中）': {k: sum(1 for t in both if R[y][t].get(k) is not None) for k in PILLARS}}
    # 社単位（最新のビンテージで1回）の A の n
    seen, nA = set(), {k: 0 for k in PILLARS}
    for y in (2015, 2013):
        for t, d in R[y].items():
            if y == 2013 and t in R.get(2015, {}):
                continue
            if None in (d['e_rt'], d['f_rt2'], d['e_rg'], d['f_rg2']):
                continue
            for k in PILLARS:
                if d.get(k) is not None:
                    nA[k] += 1
    out['A']['社単位の n（O1t と O1g がそろう）'] = nA
    # B の社単位の n（O1t の母集団に入った最新のビンテージで1回・その年に部品があるか）
    seenB, nB = set(), {k: 0 for k in COMPS + REFS_B}
    for y in (2015, 2014, 2013, 2012):
        for c in U[y]['O1t']:
            if c in seenB:
                continue
            seenB.add(c)
            for k in COMPS + REFS_B:
                if V[y][c].get(k) is not None:
                    nB[k] += 1
    out['B']['社単位の n（O1t）'] = {'社': len(seenB), **nB}
    return out


def self_check_s2(V):
    """S2: この表ののれん込み ROIC の前方（+6〜+10年の中央値）が retro_cohort の fwd_roic_med5_a2 と順位でそろうか（≥0.85）"""
    got = {}
    for y in (2013, 2015):
        co = {str(r['cik']): r for r in json.load(open(os.path.join(OUT, f'retro_cohort_{y}.json')))['rows'] if r.get('cik')}
        a, b = [], []
        for c, d in V[y].items():
            r = co.get(c)
            if r and r.get('fwd_roic_med5_a2') is not None and d['f_rg2'] is not None:
                a.append(d['f_rg2']); b.append(r['fwd_roic_med5_a2'])
        rho = MP.spear(a, b)
        got[str(y)] = {'n': len(a), 'rho': r3(rho)}
        if rho is None or rho < 0.85:
            raise SystemExit(f'✗ 自己検問 S2: {y} ののれん込み ROIC の前方が retro_cohort とそろわない（{got[str(y)]}）')
    return got


def part_A(R):
    """A: moat_persist_test と同じ道具（社単位・ビンテージの中の置換・Holm）で、O1t・O1g（同じ社）と O2m・O3t を裁く"""
    Dsub = {y: R[y] for y in READ_V}
    both = {y: [t for t, d in R[y].items() if None not in (d['e_rt'], d['f_rt2'], d['e_rg'], d['f_rg2'])] for y in READ_V}
    S_ = {}
    for y in READ_V:
        S_[y] = {}
        for o, (e, f, _) in OUTC.items():
            keys = both[y] if o in ('O1t', 'O1g') else [t for t in R[y] if R[y][t][e] is not None and R[y][t][f] is not None]
            pct, n, r2 = pct_of(R[y], keys, e, f)
            S_[y][o] = {'pct': pct, 'n': n, 'r2_entry': r2}
    res = {'母集団（驚きを作った社の数）': {str(y): {o: S_[y][o]['n'] for o in OUTC} for y in READ_V},
           '入口が前方を予言した割合（順位の R²）': {str(y): {o: S_[y][o]['r2_entry'] for o in OUTC} for y in READ_V}}
    read13 = set(R[2013])
    prim, pv = {}, {}
    for i, k in enumerate(PILLARS):
        a, b, st, tk = MP.pooled(Dsub, S_, 'O1t', k)
        mode = max((a.count(v) for v in set(a)), default=0) / max(1, len(a))
        rec = {'n_社単位': len(a), '最頻値の占有': round(mode, 3)}
        if mode >= MODE_CAP:
            rec['判定'] = '測れない（最頻値の占有≥0.85）'
        elif len(a) < MIN_N_A:
            rec['判定'] = '判定不能（n<150）'
        else:
            r, p = MP.perm(a, b, st, SEED_A + i)
            rec.update(rho=round(r, 3), p=round(p, 4))
            pv[k] = p
        a15, b15 = MP.vint(Dsub, S_, 'O1t', k, 2015)
        a13, b13 = MP.vint(Dsub, S_, 'O1t', k, 2013)
        ao, bo = MP.vint(Dsub, S_, 'O1t', k, 2015, only=set(R[2015]) - read13)
        rec['2015だけ'] = {'n': len(a15), 'rho': r3(MP.spear(a15, b15))}
        rec['2013だけ'] = {'n': len(a13), 'rho': r3(MP.spear(a13, b13))}
        rec['2015の厳密OOS（2013で読んでいない社）'] = {'n': len(ao), 'rho': r3(MP.spear(ao, bo))}
        rec['刻みごと（社単位）'] = MP.grade_table(a, b)
        # 同じ社ののれん込み（O1g）——切り分けの対照
        ag, bg, sg, _ = MP.pooled(Dsub, S_, 'O1g', k)
        if len(ag) >= 30:
            rg, pg = MP.perm(ag, bg, sg, SEED_A + 50 + i)
            rec['同じ社ののれん込み（O1g）'] = {'n': len(ag), 'rho': round(rg, 3), 'p': round(pg, 4),
                                          '刻みごと': MP.grade_table(ag, bg)}
        prim[k] = rec
    adj = MP.holm(pv)
    for k in pv:
        rec = prim[k]
        rec['p_Holm'] = round(adj[k], 4)
        c1 = rec['rho'] > 0 and adj[k] < 0.05
        if rec['2013だけ']['n'] >= MIN_N_VINT:
            c23 = (rec['2015だけ']['rho'] or 0) > 0 and (rec['2013だけ']['rho'] or 0) > 0
            how = '②2015 ρ>0 ③2013 ρ>0'
        else:
            c23 = (rec['2015の厳密OOS（2013で読んでいない社）']['rho'] or 0) > 0
            how = '②③の代わりに 2015 の厳密OOS ρ>0（2013 の n<100）'
        if c1 and c23:
            rec['判定'] = '合格（のれん・無形を除く ROIC の持続を当てる）'
        elif rec['rho'] < 0 and rec['p'] < 0.05:
            rec['判定'] = '逆（高い段ほど資本利益率が残らない）'
        else:
            why = []
            if not rec['rho'] > 0:
                why.append('社単位の ρ が正でない')
            elif not adj[k] < 0.05:
                why.append(f'Holm 調整の p={adj[k]:.3f} が0.05に届かない')
            if not c23:
                why.append(f'符号の再現（{how}）を満たさない')
            rec['判定'] = '不合格（' + '・'.join(why) + '）'
        rec['再現の条件'] = how
    passed = [k for k in ('irr', 'rep', 'dur') if str(prim.get(k, {}).get('判定', '')).startswith('合格')]
    verdict = ('支持' if len(passed) >= 2 else '一部' if len(passed) == 1 else '不支持')
    contrast = {}
    for k in passed:
        g = prim[k].get('同じ社ののれん込み（O1g）') or {}
        if g.get('rho') is not None:
            dlt = prim[k]['rho'] - g['rho']
            contrast[k] = {'rho_O1t': prim[k]['rho'], 'rho_O1g': g['rho'], '差': round(dlt, 3),
                           '読み': ('のれんが薄めた（O1g が 0.05 以上小さい）' if dlt >= 0.05
                                  else '同程度＝① の不合格は材料（retro_cohort）か標本の違い')}
    res['主の判定（O1t）'] = prim
    res['仮説 H-a（① の不合格は のれん＝買収が資本利益率を薄めたせい）'] = {
        '決まり': '①で利益率を当てた3本（irr・rep・dur）のうち2本以上が O1t で合格→支持／1本→一部／0本→不支持。'
                '合格した柱は同じ社の O1g と並べ、O1g の ρ が 0.05 以上小さければ『のれんが薄めた』、同程度なら『材料か標本の違い』と読む',
        '合格した柱': passed, '判定': verdict, '同じ社の O1g との対比': contrast}
    # 副: 目的変数ごと（参考の3つと部品も）
    sec = {}
    for oi, o in enumerate(OUTC):
        sec[o] = {'説明': OUTC[o][2]}
        for i, k in enumerate(PILLARS + REFS_A + COMPS + REFS_B):
            a, b, st, _ = MP.pooled(Dsub, S_, o, k)
            if len(a) < 30:
                sec[o][k] = {'n': len(a), 'note': 'n<30'}
                continue
            r, p = MP.perm(a, b, st, SEED_A + 1000 * (oi + 1) + i)
            a15, b15 = MP.vint(Dsub, S_, o, k, 2015)
            a13, b13 = MP.vint(Dsub, S_, o, k, 2013)
            sec[o][k] = {'n': len(a), 'rho': round(r, 3), 'p': round(p, 4),
                         'rho_2015': r3(MP.spear(a15, b15)), 'rho_2013': r3(MP.spear(a13, b13))}
    res['副: 目的変数ごと（社単位・置換の p は調整なし）'] = sec
    # 副: 部品は柱に情報を足すか（社単位・偏順位相関）
    inc = {}
    for o in ('O1t', 'O2m'):
        inc[o] = {}
        for k in COMPS:
            for ctl in ('moat_today', 'irr', 'moat5'):
                xa, ya, za = [], [], []
                for y in (2015, 2013):
                    for t, d in R[y].items():
                        if y == 2013 and t in R[2015]:
                            continue
                        pct = S_[y][o]['pct']
                        if t in pct and d.get(k) is not None and d.get(ctl) is not None:
                            xa.append(d[k]); ya.append(pct[t]); za.append(d[ctl])
                if len(xa) >= 30:
                    inc[o][f'{k}｜{ctl}'] = {'n': len(xa), '部品の偏相関（柱を除く）': r3(MP.partial(xa, ya, za)),
                                            '柱の偏相関（部品を除く）': r3(MP.partial(za, ya, xa))}
    res['副: 部品と柱の足し合い（偏順位相関・社単位）'] = inc
    return res


def part_B(V, sic, U):
    res = {'母集団': {str(y): {o: len(U[y][o]) for o in OUTC} for y in VINT}}
    P = {}
    r2s = {}
    for y in VINT:
        P[y] = {}
        r2s[str(y)] = {}
        for o, (e, f, _) in OUTC.items():
            pct, n, r2 = pct_of(V[y], U[y][o], e, f)
            P[y][o] = pct
            r2s[str(y)][o] = r2
    res['入口が前方を予言した割合（順位の R²）'] = r2s
    tab = {}
    for oi, o in enumerate(OUTC):
        tab[o] = {}
        for ci, k in enumerate(COMPS + REFS_B):
            row = {}
            for vi, y in enumerate(VINT):
                ks = [c for c in P[y][o] if V[y][c].get(k) is not None]
                x = [V[y][c][k] for c in ks]
                yy = [P[y][o][c] for c in ks]
                r, p = rho_p(x, yy, SEED_B + 1000 * oi + 100 * ci + vi)
                row[str(y)] = {'n': len(ks), 'rho': r3(r), 'p': None if p is None else round(p, 4)}
            tab[o][k] = row
    res['表: 部品×目的変数×ビンテージ（ρ・置換の p は調整なし）'] = tab
    # 主の判定（O1t・社単位＝各社は最新のビンテージで1回・ビンテージの中の置換・Holm・4つのビンテージで符号）
    prim, pv = {}, {}
    for ci, k in enumerate(COMPS):
        a, b, st = pooled_B(V, P, k)
        rec = {'n_社単位': len(a), 'ビンテージ別': {str(y): tab['O1t'][k][str(y)] for y in VINT}}
        if len(a) < MIN_N_B:
            rec['判定'] = f'判定不能（社単位の n<{MIN_N_B}）'
        else:
            r, p = rho_p(a, b, SEED_B + 90000 + ci, strata=st)
            rec.update(rho=r3(r), p=round(p, 4))
            pv[k] = p
        prim[k] = rec
    adj = MP.holm(pv)
    for k in pv:
        rec = prim[k]
        rec['p_Holm'] = round(adj[k], 4)
        c_a = rec['rho'] >= FLOOR and adj[k] < 0.05
        c_b = all((rec['ビンテージ別'][str(y)]['rho'] or 0) > 0 for y in VINT)
        if c_a and c_b:
            rec['判定'] = '合格（のれん・無形を除く ROIC の持続を当てる）'
        elif rec['rho'] <= -FLOOR and adj[k] < 0.05:
            rec['判定'] = '逆（高いほど持続しない）'
        else:
            why = []
            if not rec['rho'] >= FLOOR:
                why.append(f'社単位の ρ={rec["rho"]:+.3f} が下限 +{FLOOR} に届かない')
            if not adj[k] < 0.05:
                why.append(f'Holm 調整の p={adj[k]:.3f} が0.05に届かない')
            if not c_b:
                why.append('4つのビンテージのどれかで符号が正でない')
            rec['判定'] = '不合格（' + '・'.join(why) + '）'
    res['主の判定（O1t・社単位）'] = prim
    res['合格した部品'] = [k for k in COMPS if str(prim[k].get('判定', '')).startswith('合格')]
    # 副: 頑健さ（O1t・2015 と 2012）
    rob = {}
    for ci, k in enumerate(COMPS + REFS_B):
        rob[k] = {}
        for vi, y in enumerate((2015, 2012)):
            pct = P[y]['O1t']
            ks = [c for c in pct if V[y][c].get(k) is not None]
            x = [V[y][c][k] for c in ks]
            # 規模を除いた偏順位相関
            sz = [math.log(V[y][c]['rev']) for c in ks]
            part = MP.partial(x, [pct[c] for c in ks], sz) if len(ks) >= 30 else None
            # 半導体に近い SIC を除く
            ks2 = [c for c in ks if (sic.get(c) or '') not in SEMI_SIC]
            r_ns, p_ns = rho_p([V[y][c][k] for c in ks2], [pct[c] for c in ks2], SEED_B + 50000 + 100 * ci + vi)
            # 業種（SIC2・5社以上）の中の順位で驚きを作り直す
            wi = within(pct, {c: (sic.get(c) or '')[:2] for c in pct})
            ks3 = [c for c in ks if c in wi]
            r_in, p_in = rho_p([V[y][c][k] for c in ks3], [wi[c] for c in ks3], SEED_B + 60000 + 100 * ci + vi)
            # 入口の水準との相関（部品がどれだけ「水準」か）
            lev = MP.spear(x, [V[y][c]['e_rt'] for c in ks]) if len(ks) >= 30 else None
            rob[k][str(y)] = {'規模を除いた偏順位相関': r3(part),
                              '半導体に近い SIC を除く': {'n': len(ks2), 'rho': r3(r_ns), 'p': p_ns},
                              '業種（SIC2）の中の順位で作り直す': {'n': len(ks3), 'rho': r3(r_in), 'p': p_in},
                              '入口の ROIC（除く）との順位相関': r3(lev)}
    res['副: 頑健さ（O1t）'] = rob
    # 副: 部品どうしの順位相関（2015・O1t の母集団）
    cor = {}
    ks0 = list(P[2015]['O1t'])
    allk = COMPS + REFS_B
    for i, k1 in enumerate(allk):
        for k2 in allk[i + 1:]:
            pa = [(V[2015][c][k1], V[2015][c][k2]) for c in ks0 if V[2015][c].get(k1) is not None and V[2015][c].get(k2) is not None]
            cor[f'{k1}×{k2}'] = {'n': len(pa), 'rho': r3(MP.spear([a for a, _ in pa], [b for _, b in pa], 30))}
    res['副: 部品どうしの順位相関（2015）'] = cor
    return res


def main():
    count_only = '--count' in sys.argv
    pan, V, sic = build(fetch_sic=True)
    U = universes(V, sic)
    D, R = read_sets(V)
    cnt = counts(V, sic, U, R)
    if count_only:
        print(json.dumps(cnt, ensure_ascii=False, indent=1))
        return
    if not os.path.exists(PRE):
        raise SystemExit('✗ 事前登録 out/moat_track_prereg.json が無い（測る前にコミットすること）')
    s1 = MTP.selfcheck()
    if s1['不一致']:
        raise SystemExit(f'✗ 自己検問 S1: backtest_core と年ごとの計算が一致しない {s1}')
    s2 = self_check_s2(V)
    res = {'generated': datetime.date.today().isoformat(), 'tool': 'night/moat_track_test.py',
           '事前登録': 'out/moat_track_prereg.json', '材料': pan['meta'],
           '自己検問': {'S1（backtest_core.pit_metrics と年ごとの計算が一致）': {k: v for k, v in s1.items() if k != '不一致の例'},
                    'S2（のれん込み ROIC の前方が retro_cohort とそろう）': s2},
           '数': cnt, '部品の定義': DESC, '目的変数': {o: v[2] for o, v in OUTC.items()}}
    res['A: のれん・無形を除いた ROIC で柱を測り直す'] = part_A(R)
    res['B: 機械で測れる実績の部品'] = part_B(V, sic, U)
    with open(os.path.join(OUT, 'moat_track.json'), 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    A, B = res['A: のれん・無形を除いた ROIC で柱を測り直す'], res['B: 機械で測れる実績の部品']
    print('自己検問', res['自己検問'])
    for k, r in A['主の判定（O1t）'].items():
        print('A', k, r.get('n_社単位'), r.get('rho'), r.get('p'), r.get('p_Holm'), r['2015だけ'], r['2013だけ'],
              r.get('同じ社ののれん込み（O1g）', {}).get('rho'), '→', r.get('判定'))
    print('H-a', A['仮説 H-a（① の不合格は のれん＝買収が資本利益率を薄めたせい）'])
    for k, r in B['主の判定（O1t・社単位）'].items():
        print('B', k, r.get('n_社単位'), r.get('rho'), r.get('p'), r.get('p_Holm'),
              {y: (v['n'], v['rho']) for y, v in r['ビンテージ別'].items()}, '→', r.get('判定'))
    print('書いた out/moat_track.json')


if __name__ == '__main__':
    main()
