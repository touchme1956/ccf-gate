#!/usr/bin/env python3
"""night/moat_repl_test.py — 堀の再現の検定: ①②の副の結果は、別の読解・別の年代でも出るか（2026-10-12新設・読むだけ）

事前登録 out/moat_repl_prereg.json のとおりに一度だけ裁く。門の採点・刻み・重み・関門・売却規律には触れない（絶対のルール1）。
決断待ち moat_redesign_1011 の続き（①moat_persist・②moat_track は主の物差し〔10年先の資本利益率の持続〕で合格0本。
副の物差し〔営業利益率の持続・1〜5年先の資本利益率〕では柱と機械の部品が効いた＝事後の読み）。ここでそれを確かめる。

A'（2018年の読解・177社・irr18 と moat5）: 2018-07-01 までの提出を読んだ読解なので、入口は 2013〜2017年（締め日 2018-07-01）。
   主＝前方 +6〜+10年（2023〜2025・3年そろうこと）の営業利益率の中央値の驚き（② の O2m と同じ定義）。
B'（機械の部品・新しい年代）: 主＝ビンテージ 2019（入口 2015〜2019・締め日 2020-07-01・前方 +1〜+5年＝2020〜2024）。
   M3・M4 → 営業利益率（+1〜+5年）、M1・M4 → のれん・無形を除く ROIC（+1〜+5年）、M5 → 両方（負の向き）。
副: ①②の柱を正しい時点（2013年の読解→入口 2008〜2012・2015年→2010〜2014）でそろえ直した値、ほか。
材料: out/_moat3_panel.json（night/moat_track_panel.py --vint 2012-2020 --out out/_moat3_panel.json）・業種 out/sic_by_cik.json
出力: out/moat_repl.json   使い方: python3 night/moat_repl_test.py --count（数だけ）／ 引数なし（本番・一度だけ）
"""
import datetime, json, math, os, statistics as S, sys

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import retro_surprise as RS        # noqa: E402  split（驚き）
import moat_persist_test as MP     # noqa: E402  load（2013・2015 の柱）・ranks・spear・partial・holm・pooled・grade_table
import moat_track_test as T        # noqa: E402  firm_vintage（入口・前方・部品）・share_trend・in_universe・rankavg・pct_of・within
import moat_track_panel as MTP     # noqa: E402  read_ciks・read_ciks_2018・selfcheck
import industry_trends as IT       # noqa: E402  sic_map

OUT = os.path.join(BASE, 'out')
PANEL = os.path.join(OUT, '_moat3_panel.json')
PANEL2 = os.path.join(OUT, '_moat2_panel.json')
PRE = os.path.join(OUT, 'moat_repl_prereg.json')
VINT_B = (2016, 2017, 2018, 2019, 2020)
PRIMARY_B = 2019
Y18 = 2017                      # 2018年の読解（2018-07-01 までの提出）＝入口 2013〜2017・締め日 2018-07-01
NPERM = 4000
SEED = 20261012
MIN_N_A, MIN_N_B, MODE_CAP = 80, 250, 0.85
FLOOR_B = 0.05
I_REV, I_OP, I_GM, I_OPM, I_RG, I_RT = range(6)
# 目的変数: (入口の欄, 前方の欄, 説明)
OUT_A = {'O2m': ('e_opm', 'f_opm2', '前方 +6〜+10年（2023〜2025）の営業利益率の中央値の驚き'),
         'O1t': ('e_rt', 'f_rt2', '前方 +6〜+10年（2023〜2025）の のれん・無形を除く ROIC の驚き'),
         'O3t': ('e_rt', 'f_rt1', '前方 +1〜+5年（2018〜2022）の のれん・無形を除く ROIC の驚き'),
         'O3m': ('e_opm', 'f_opm1', '前方 +1〜+5年（2018〜2022）の営業利益率の驚き'),
         'O48m': ('e_opm', 'f_opm48', '前方 +4〜+8年（2021〜2025）の営業利益率の驚き'),
         'O48t': ('e_rt', 'f_rt48', '前方 +4〜+8年（2021〜2025）の のれん・無形を除く ROIC の驚き')}
OUT_B = {'O3m': ('e_opm', 'f_opm1', '前方 +1〜+5年の営業利益率の中央値の驚き'),
         'O3t': ('e_rt', 'f_rt1', '前方 +1〜+5年の のれん・無形を除く ROIC の驚き'),
         'O2m': ('e_opm', 'f_opm2', '前方 +6〜+10年の営業利益率の驚き（2016・2017 だけ・前方は2025で切れる）'),
         'O1t': ('e_rt', 'f_rt2', '前方 +6〜+10年の のれん・無形を除く ROIC の驚き（2016・2017 だけ）')}
# 主の仮説（向き +1/−1）
PRIM_A = [('irr', 'O2m', +1), ('moat5', 'O2m', +1)]
PRIM_B = [('M3', 'O3m', +1), ('M4', 'O3m', +1), ('M1', 'O3t', +1), ('M4', 'O3t', +1), ('M5', 'O3m', -1), ('M5', 'O3t', -1)]
COMPS = ['M1', 'M2', 'M3', 'M4', 'M5', 'R1', 'R2', 'R3', 'R4', 'Cm', 'Ct']
SEMI_SIC = T.SEMI_SIC


def firm_vintage_x(f, Y):
    """moat_track_test.firm_vintage に、+1〜+5年の営業利益率と +4〜+8年の窓を足す"""
    d = T.firm_vintage(f, Y)
    L = f['latest']
    a1, w48 = range(Y + 1, Y + 6), range(Y + 4, Y + 9)
    d['f_opm1'] = T.med(T.win(L, a1, I_OPM, 3))
    d['f_opm48'] = T.med(T.win(L, w48, I_OPM, 3))
    d['f_rt48'] = T.med(T.win(L, w48, I_RT, 3))
    return d


def composites(V):
    """参考の合成（判定に使わない）: Cm＝M3 と M4 の順位の割合の平均（営業利益率向け）／Ct＝M1 と M4（ROIC 向け）。ビンテージの中の順位"""
    for key, (a, b) in (('Cm', ('M3', 'M4')), ('Ct', ('M1', 'M4'))):
        ks = [c for c, d in V.items() if d.get(a) is not None and d.get(b) is not None]
        if len(ks) < 20:
            for d in V.values():
                d[key] = None
            continue
        ra, rb = T.rankavg([V[c][a] for c in ks]), T.rankavg([V[c][b] for c in ks])
        for d in V.values():
            d[key] = None
        for i, c in enumerate(ks):
            V[c][key] = float((ra[i] + rb[i]) / 2.0 / len(ks))


def rho_p1(x, y, seed, sign=+1, strata=None):
    """Spearman ρ と置換の片側 p（向き sign の方向に観測以上の割合）。両側も返す"""
    if len(x) < 20:
        return None, None, None
    rx, ry = T.rankavg(x), T.rankavg(y)
    rx = (rx - rx.mean()) / (rx.std() or 1)
    ry = (ry - ry.mean()) / (ry.std() or 1)
    n = len(rx)
    obs = float(rx @ ry / n)
    rng = np.random.default_rng(seed)
    groups = None
    if strata is not None:
        st = np.asarray(strata)
        groups = [np.where(st == s)[0] for s in np.unique(st)]
    one = two = 0
    yy = ry.copy()
    for _ in range(NPERM):
        if groups is None:
            yy = rng.permutation(ry)
        else:
            for g in groups:
                yy[g] = rng.permutation(ry[g])
        r = float(rx @ yy / n)
        if sign * r >= sign * obs - 1e-12:
            one += 1
        if abs(r) >= abs(obs) - 1e-12:
            two += 1
    return obs, one / NPERM, two / NPERM


def r3(v):
    return None if v is None else round(v, 3)


def load_panel():
    return json.load(open(PANEL))


def build(pan, fetch_sic=True):
    F = pan['firms']
    years = sorted(set(VINT_B) | {Y18, 2012, 2014})
    V = {y: {} for y in years}
    for c, f in F.items():
        for y in years:
            if str(y) in f['pit']:
                V[y][c] = firm_vintage_x(f, y)
    need = sorted({int(c) for y in VINT_B for c, d in V[y].items() if d['rev'] is not None and d['rev'] >= T.MIN_REV})
    sic = {str(k): v for k, v in IT.sic_map(need, fetch=fetch_sic).items()}
    for y in years:
        U = {c: d for c, d in V[y].items() if T.in_universe(d, sic.get(c))}
        T.share_trend(U, sic)
        for d in V[y].values():
            d.setdefault('M5', None)
        composites(U)
        for d in V[y].values():
            d.setdefault('Cm', None)
            d.setdefault('Ct', None)
    return V, sic


def reads_2018(V):
    """2018年の読解（先勝ち: retro_moat_2018 → _rest）と、表のビンテージ 2017 の入口・前方"""
    _k, t2c = MTP.read_ciks_2018()
    R, seen = {}, set()
    for fn in ('retro_moat_2018.json', 'retro_moat_2018_rest.json'):
        d = json.load(open(os.path.join(OUT, fn)))
        for r in (d['rows'] if isinstance(d, dict) and 'rows' in d else d):
            t = r.get('t') or r.get('ticker')
            if not t or t in seen:
                continue
            seen.add(t)
            v = V[Y18].get(str(t2c[t]))
            if v is None:
                continue
            R[t] = dict(v, irr=MP.num(r.get('irr18')), moat5=MP.num(r.get('moat5')), dom=MP.num(r.get('dom18')), cik=str(t2c[t]))
    return R


def reads_insample(V):
    """①②の読解（2013・2015）を正しい時点にそろえる: 2013年の読解→表のビンテージ 2012、2015年→2014（キーは読解の年のまま）"""
    D = MP.load()
    _k, t2c = MTP.read_ciks()
    R = {}
    for ry, py in ((2013, 2012), (2015, 2014)):
        R[ry] = {}
        for t, p in D[ry].items():
            v = V[py].get(str(t2c.get(t)))
            if v is None:
                continue
            keep = {k: p.get(k) for k in ('irr', 'rep', 'dur', 'moatW', 'dom', 'moat5', 'moat_today', 'irr_today', 'semi', 'sic2')}
            R[ry][t] = dict(v, **keep)
    return R


def universes_B(V, sic):
    U = {}
    for y in VINT_B:
        base = [c for c, d in V[y].items() if T.in_universe(d, sic.get(c))]
        U[y] = {o: [c for c in base if V[y][c][e] is not None and V[y][c][f] is not None] for o, (e, f, _) in OUT_B.items()}
        U[y]['_base'] = base
    return U


def counts(V, sic, U, R18, RIN):
    out = {'A_2018読解': {'読解の社（表にある）': len(R18)}, 'B': {}, '①②のそろえ直し': {}}
    for o, (e, f, _) in OUT_A.items():
        ks = [t for t, d in R18.items() if d[e] is not None and d[f] is not None]
        out['A_2018読解'][o] = {'n': len(ks), 'irr': sum(1 for t in ks if R18[t]['irr'] is not None),
                              'moat5': sum(1 for t in ks if R18[t]['moat5'] is not None)}
    for y in VINT_B:
        out['B'][str(y)] = {o: len(U[y][o]) for o in OUT_B}
        out['B'][str(y)]['母集団'] = len(U[y]['_base'])
        out['B'][str(y)]['部品の被覆（O3t の母集団の中）'] = {k: sum(1 for c in U[y]['O3t'] if V[y][c].get(k) is not None) for k in COMPS}
        out['B'][str(y)]['部品の被覆（O3m の母集団の中）'] = {k: sum(1 for c in U[y]['O3m'] if V[y][c].get(k) is not None) for k in COMPS}
    for ry in (2013, 2015):
        out['①②のそろえ直し'][str(ry)] = {}
        for o in ('O2m', 'O1t', 'O3t', 'O3m'):
            e, f = OUT_A[o][:2]
            out['①②のそろえ直し'][str(ry)][o] = sum(1 for d in RIN[ry].values() if d[e] is not None and d[f] is not None)
    return out


def s2_same_as_moat2(pan):
    """S2: 広げた表の 2012〜2015 と今日の数字が、② の表（out/_moat2_panel.json）と全社で一致すること"""
    if not os.path.exists(PANEL2):
        raise SystemExit('✗ 自己検問 S2: out/_moat2_panel.json が無い（night/moat_track_panel.py で作り直す）')
    a = json.load(open(PANEL2))['firms']
    b = pan['firms']
    bad = [k for k, f in a.items() if k not in b or f['latest'] != b[k]['latest']
           or any(f['pit'].get(y) != b[k]['pit'].get(y) for y in ('2012', '2013', '2014', '2015'))]
    if bad:
        raise SystemExit(f'✗ 自己検問 S2: ② の表と食い違う社 {len(bad)}（例 {bad[:5]}）')
    return {'② の表の社': len(a), '食い違い': 0, '広げた表の社': len(b)}


def part_A(R18):
    res = {'母集団（驚きを作った社の数）': {}, '入口が前方を予言した割合（順位の R²）': {}}
    P = {}
    for o, (e, f, _) in OUT_A.items():
        ks = [t for t, d in R18.items() if d[e] is not None and d[f] is not None]
        P[o], n, r2 = T.pct_of(R18, ks, e, f)
        res['母集団（驚きを作った社の数）'][o] = n
        res['入口が前方を予言した割合（順位の R²）'][o] = r2
    prim, pv = {}, {}
    for i, (k, o, sg) in enumerate(PRIM_A):
        ks = [t for t in P[o] if R18[t].get(k) is not None]
        x = [R18[t][k] for t in ks]
        mode = max((x.count(v) for v in set(x)), default=0) / max(1, len(x))
        rec = {'仮説': f'{k} → {o}（向き {"+" if sg > 0 else "−"}）', 'n': len(ks), '最頻値の占有': round(mode, 3)}
        if mode >= MODE_CAP:
            rec['判定'] = '測れない（最頻値の占有≥0.85）'
        elif len(ks) < MIN_N_A:
            rec['判定'] = f'判定不能（n<{MIN_N_A}）'
        else:
            r, p1, p2 = rho_p1(x, [P[o][t] for t in ks], SEED + i, sg)
            rec.update(rho=r3(r), p_片側=round(p1, 4), p_両側=round(p2, 4))
            pv[f'{k}|{o}'] = p1
        rec['刻みごと'] = MP.grade_table(x, [P[o][t] for t in ks]) if len(ks) >= 5 else None
        prim[f'{k}|{o}'] = rec
    adj = MP.holm(pv)
    for key in pv:
        rec = prim[key]
        sg = dict(((k + '|' + o), s) for k, o, s in PRIM_A)[key]
        rec['p_Holm'] = round(adj[key], 4)
        if sg * rec['rho'] > 0 and adj[key] < 0.05:
            rec['判定'] = '再現した'
        elif -sg * rec['rho'] > 0 and rec['p_両側'] < 0.05:
            rec['判定'] = '逆向き（再現しない）'
        else:
            rec['判定'] = '再現しなかった（' + ('向きが逆' if sg * rec['rho'] <= 0 else f'Holm 調整の片側 p={adj[key]:.3f}') + '）'
    res['主の判定'] = prim
    sec = {}
    for oi, o in enumerate(OUT_A):
        sec[o] = {'説明': OUT_A[o][2]}
        for j, k in enumerate(['irr', 'moat5', 'dom'] + COMPS):
            ks = [t for t in P[o] if R18[t].get(k) is not None]
            if len(ks) < 30:
                sec[o][k] = {'n': len(ks), 'note': 'n<30'}
                continue
            r, p1, p2 = rho_p1([R18[t][k] for t in ks], [P[o][t] for t in ks], SEED + 100 * (oi + 1) + j, +1)
            sec[o][k] = {'n': len(ks), 'rho': r3(r), 'p_両側': round(p2, 4)}
    res['副: 目的変数ごと（読解の社・置換の p は調整なし）'] = sec
    # 副: 規模を除いた偏順位相関（主の2本）・読解と機械の合成の足し合い
    extra = {}
    for k, o, _ in PRIM_A:
        ks = [t for t in P[o] if R18[t].get(k) is not None and R18[t].get('rev')]
        if len(ks) >= 30:
            extra[f'{k}|{o}｜規模'] = r3(MP.partial([R18[t][k] for t in ks], [P[o][t] for t in ks], [math.log(R18[t]['rev']) for t in ks]))
        for ctl in ('Cm', 'M3', 'M4'):
            kk = [t for t in ks if R18[t].get(ctl) is not None]
            if len(kk) >= 30:
                extra[f'{k}|{o}｜{ctl}'] = {'n': len(kk), '読解の偏相関（機械を除く）': r3(MP.partial([R18[t][k] for t in kk], [P[o][t] for t in kk], [R18[t][ctl] for t in kk])),
                                           '機械の偏相関（読解を除く）': r3(MP.partial([R18[t][ctl] for t in kk], [P[o][t] for t in kk], [R18[t][k] for t in kk]))}
    res['副: 規模・機械の部品を除いた偏順位相関'] = extra
    return res


def part_A_insample(RIN):
    """副: ①②の柱を正しい時点にそろえ直す（2013年の読解→ビンテージ 2012・2015年→2014）。社単位（2015年に読んだ社は 2015）・ビンテージの中の置換（両側）"""
    S_ = {}
    for ry in (2013, 2015):
        S_[ry] = {}
        for o in ('O2m', 'O1t', 'O3t', 'O3m'):
            e, f = OUT_A[o][:2]
            ks = [t for t, d in RIN[ry].items() if d[e] is not None and d[f] is not None]
            pct, n, r2 = T.pct_of(RIN[ry], ks, e, f)
            S_[ry][o] = {'pct': pct, 'n': n, 'r2_entry': r2}
    res = {'母集団': {str(ry): {o: S_[ry][o]['n'] for o in S_[ry]} for ry in S_}}
    tab = {}
    for oi, o in enumerate(('O2m', 'O1t', 'O3t', 'O3m')):
        tab[o] = {}
        for j, k in enumerate(['irr', 'rep', 'dur', 'moatW', 'moat5', 'moat_today', 'irr_today', 'M1', 'M3', 'M4', 'M5', 'Cm', 'Ct']):
            a, b, st, _ = MP.pooled(RIN, S_, o, k)
            if len(a) < 30:
                tab[o][k] = {'n': len(a), 'note': 'n<30'}
                continue
            r, p1, p2 = rho_p1(a, b, SEED + 5000 + 100 * oi + j, +1, strata=st)
            a15, b15 = MP.vint(RIN, S_, o, k, 2015)
            a13, b13 = MP.vint(RIN, S_, o, k, 2013)
            tab[o][k] = {'n': len(a), 'rho': r3(r), 'p_両側': round(p2, 4),
                         'rho_2015': r3(MP.spear(a15, b15)), 'rho_2013': r3(MP.spear(a13, b13))}
    res['表'] = tab
    return res


def part_B(V, sic, U):
    P = {}
    r2s = {}
    for y in VINT_B:
        P[y], r2s[str(y)] = {}, {}
        for o, (e, f, _) in OUT_B.items():
            pct, n, r2 = T.pct_of(V[y], U[y][o], e, f)
            P[y][o] = pct
            r2s[str(y)][o] = r2
    res = {'母集団': {str(y): {o: len(U[y][o]) for o in OUT_B} for y in VINT_B}, '入口が前方を予言した割合（順位の R²）': r2s}
    tab = {}
    for oi, o in enumerate(OUT_B):
        tab[o] = {}
        for ci, k in enumerate(COMPS):
            row = {}
            for vi, y in enumerate(VINT_B):
                ks = [c for c in P[y][o] if V[y][c].get(k) is not None]
                r, p1, p2 = rho_p1([V[y][c][k] for c in ks], [P[y][o][c] for c in ks], SEED + 20000 + 1000 * oi + 100 * ci + vi, +1)
                row[str(y)] = {'n': len(ks), 'rho': r3(r), 'p_両側': None if p2 is None else round(p2, 4)}
            tab[o][k] = row
    res['表: 部品×目的変数×ビンテージ（ρ・置換の p は調整なし）'] = tab
    prim, pv = {}, {}
    for i, (k, o, sg) in enumerate(PRIM_B):
        ks = [c for c in P[PRIMARY_B][o] if V[PRIMARY_B][c].get(k) is not None]
        rec = {'仮説': f'{k} → {o}（向き {"+" if sg > 0 else "−"}）', 'n': len(ks)}
        if len(ks) < MIN_N_B:
            rec['判定'] = f'判定不能（n<{MIN_N_B}）'
        else:
            r, p1, p2 = rho_p1([V[PRIMARY_B][c][k] for c in ks], [P[PRIMARY_B][o][c] for c in ks], SEED + 40000 + i, sg)
            rec.update(rho=r3(r), p_片側=round(p1, 4), p_両側=round(p2, 4))
            pv[f'{k}|{o}'] = p1
        rec['2017・2018 の ρ'] = {str(y): tab[o][k][str(y)]['rho'] for y in (2017, 2018)}
        prim[f'{k}|{o}'] = rec
    adj = MP.holm(pv)
    sgn = {f'{k}|{o}': s for k, o, s in PRIM_B}
    for key in pv:
        rec = prim[key]
        sg = sgn[key]
        rec['p_Holm'] = round(adj[key], 4)
        c1 = sg * rec['rho'] >= FLOOR_B and adj[key] < 0.05
        c2 = all((sg * (rec['2017・2018 の ρ'][y] or 0)) > 0 for y in ('2017', '2018'))
        if c1 and c2:
            rec['判定'] = '再現した'
        elif -sg * rec['rho'] >= FLOOR_B and rec['p_両側'] < 0.05:
            rec['判定'] = '逆向き（再現しない）'
        else:
            why = []
            if not sg * rec['rho'] >= FLOOR_B:
                why.append(f'向きをそろえた ρ={sg * rec["rho"]:+.3f} が下限 +{FLOOR_B} に届かない')
            if not adj[key] < 0.05:
                why.append(f'Holm 調整の片側 p={adj[key]:.3f}')
            if not c2:
                why.append('2017・2018 のどちらかで向きが合わない')
            rec['判定'] = '再現しなかった（' + '・'.join(why) + '）'
    res[f'主の判定（ビンテージ {PRIMARY_B}）'] = prim
    rob = {}
    for ci, k in enumerate(['M1', 'M3', 'M4', 'M5', 'Cm', 'Ct']):
        rob[k] = {}
        for o in ('O3m', 'O3t'):
            pct = P[PRIMARY_B][o]
            ks = [c for c in pct if V[PRIMARY_B][c].get(k) is not None]
            if len(ks) < 30:
                continue
            x = [V[PRIMARY_B][c][k] for c in ks]
            sz = [math.log(V[PRIMARY_B][c]['rev']) for c in ks]
            ks2 = [c for c in ks if (sic.get(c) or '') not in SEMI_SIC]
            r_ns, _p1, p_ns = rho_p1([V[PRIMARY_B][c][k] for c in ks2], [pct[c] for c in ks2], SEED + 60000 + 10 * ci, +1)
            wi = T.within(pct, {c: (sic.get(c) or '')[:2] for c in pct})
            ks3 = [c for c in ks if c in wi]
            r_in, _p1, p_in = rho_p1([V[PRIMARY_B][c][k] for c in ks3], [wi[c] for c in ks3], SEED + 70000 + 10 * ci, +1)
            rob[k][o] = {'規模を除いた偏順位相関': r3(MP.partial(x, [pct[c] for c in ks], sz)),
                         '半導体に近い SIC を除く': {'n': len(ks2), 'rho': r3(r_ns), 'p_両側': p_ns},
                         '業種（SIC2）の中の順位': {'n': len(ks3), 'rho': r3(r_in), 'p_両側': p_in},
                         '入口の水準との順位相関': r3(MP.spear(x, [V[PRIMARY_B][c][OUT_B[o][0]] for c in ks]))}
    res[f'副: 頑健さ（ビンテージ {PRIMARY_B}）'] = rob
    return res


def main():
    count_only = '--count' in sys.argv
    pan = load_panel()
    V, sic = build(pan, fetch_sic=True)
    U = universes_B(V, sic)
    R18 = reads_2018(V)
    RIN = reads_insample(V)
    cnt = counts(V, sic, U, R18, RIN)
    if count_only:
        print(json.dumps(cnt, ensure_ascii=False, indent=1))
        return
    if not os.path.exists(PRE):
        raise SystemExit('✗ 事前登録 out/moat_repl_prereg.json が無い（測る前にコミットすること）')
    s1 = MTP.selfcheck()
    if s1['不一致']:
        raise SystemExit(f'✗ 自己検問 S1: backtest_core と年ごとの計算が一致しない {s1}')
    s2 = s2_same_as_moat2(pan)
    res = {'generated': datetime.date.today().isoformat(), 'tool': 'night/moat_repl_test.py', '事前登録': 'out/moat_repl_prereg.json',
           '材料': pan['meta'], '自己検問': {'S1（backtest_core と一致）': {k: v for k, v in s1.items() if k != '不一致の例'},
                                        'S2（② の表と同じ部分が一致）': s2}, '数': cnt}
    res["A': 2018年の読解（irr18・moat5）"] = part_A(R18)
    res["B': 新しい年代の機械の部品"] = part_B(V, sic, U)
    res['副: ①②の柱を正しい時点でそろえ直す'] = part_A_insample(RIN)
    with open(os.path.join(OUT, 'moat_repl.json'), 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print('自己検問', res['自己検問'])
    for key, r in res["A': 2018年の読解（irr18・moat5）"]['主の判定'].items():
        print("A'", key, r.get('n'), r.get('rho'), r.get('p_片側'), r.get('p_Holm'), '→', r.get('判定'))
    for key, r in res["B': 新しい年代の機械の部品"][f'主の判定（ビンテージ {PRIMARY_B}）'].items():
        print("B'", key, r.get('n'), r.get('rho'), r.get('p_片側'), r.get('p_Holm'), r.get('2017・2018 の ρ'), '→', r.get('判定'))
    print('書いた out/moat_repl.json')


if __name__ == '__main__':
    main()
