#!/usr/bin/env python3
"""night/moat_repl_posthoc.py — 堀の再現の検定（moat_repl）の事後の診断（2026-10-12・結果を見た後に足した・判定に使わない・読むだけ）

moat_repl（事前登録 out/moat_repl_prereg.json・結果 out/moat_repl.json）の判定は動かさない。ここは結果を見た後に気づいた2点を測るだけ。
D1 売上の穴: 表（out/_moat3_panel.json）の『その時点の数字』は売上の候補タグを gate0 の接ぎ規則（年数の多い候補が主・重なる年が2%以内で
   一致するときだけ欠けた年を埋める）で1本にしている。2016年以降のビンテージでは、古いタグが主になり新しいタグの年が継ぎ目の検問で落ちる社が
   増える（営業利益はあるのに年 Y の売上が無い・今日の売上2億ドル以上の社: 2012〜2015 0〜16社 → 2016〜2020 93〜167社）。② は『今日の数字』
   だけ候補を2013年以降に絞って直した（moat_track_panel.merged の ymin）が、その時点の数字には同じ穴が残っていた。
   → 主系列を『年 Y を持つ候補（同数なら年数の多い候補）』にした表（out/_moat3v_panel.json・gitignore）を作り、主の判定と同じ計算を回し直す。
D2 直近の年の水準: 驚きは『入口の5年の中央値』を錨にする。直近の年が中央値より上の社（利益率が上向きの社）は、前方が中央値より上に出やすい
   ＝錨の取り方だけで正の驚きになる。粗利率の下落幅 M4（年 Y の粗利率−その前4年の最高）はまさに『直近が高いか』の量なので、
   M4 の効きがこの仕組みの写しかを確かめる: ①錨に直近の年の水準を足した驚き（前方の順位を入口と直近の年の順位で回帰した残差）
   ②直近の年の偏り（年 Y の値−入口の中央値）を除いた偏順位相関 ③錨を入口の3次式にした驚き（M1 は入口の水準と0.88で重なる＝曲がりの写しか）。
使い方: python3 night/moat_repl_posthoc.py --build（D1 の表を作る・4並列・数分）／ python3 night/moat_repl_posthoc.py（診断・out/moat_repl_posthoc.json）
"""
import datetime, json, multiprocessing as mp, os, sys, time, zipfile

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import backtest_core as BC                 # noqa: E402
import retro_growth_persistence as RGP     # noqa: E402
import moat_track_panel as MTP             # noqa: E402
import moat_track_test as T                # noqa: E402
import moat_persist_test as MP             # noqa: E402
import moat_repl_test as R                 # noqa: E402

OUT = os.path.join(BASE, 'out')
PANEL_V = os.path.join(OUT, '_moat3v_panel.json')
OUTF = os.path.join(OUT, 'moat_repl_posthoc.json')
VINT_ALL = tuple(range(2012, 2021))
_ORIG_MERGED = MTP.merged


def merged_pref(j, tags, cutoff, ymin=None):
    """その時点の数字（締め日あり）だけ: 主系列＝年 Y（締め日の年−1）を持つ候補、同数なら年数の多い候補（並びが同じなら候補の一覧の順）。
       継ぎ目の検問（重なる年が2%以内）は gate0 と同じ。今日の数字（締め日なし）は元のまま"""
    if cutoff is None:
        return _ORIG_MERGED(j, tags, cutoff, ymin)
    Y = int(cutoff[:4]) - 1
    cands = []
    for t in tags:
        d = BC.annual_rows(j, t, cutoff)
        if ymin is not None:
            d = {y: v for y, v in d.items() if y >= ymin}
        if d:
            cands.append((t, d))
    if not cands:
        return {}
    cands = sorted(cands, key=lambda c: (-(Y in c[1]), -len(c[1])))
    merged = dict(cands[0][1])
    for _t, d in cands[1:]:
        overlap = [y for y in merged if y in d]
        if not all(merged[y] == 0 or abs(d[y] - merged[y]) / abs(merged[y]) <= RGP.SEAM_TOL for y in overlap):
            continue
        for y, v in d.items():
            if y not in merged:
                merged[y] = v
    return merged


def build_variant():
    MTP.merged = merged_pref          # fork で子へ引き継ぐ（Linux の既定）
    MTP.set_vint(VINT_ALL)
    keep = MTP.read_ciks()[0] | MTP.read_ciks_2018()[0]
    names = [n for n in zipfile.ZipFile(MTP.ZIP).namelist() if n.startswith('CIK') and n.endswith('.json')]
    t0, res = time.time(), {}
    with mp.Pool(4, initializer=MTP._init, initargs=(VINT_ALL,)) as pool:
        for i, r in enumerate(pool.imap_unordered(MTP.work, [(n, keep) for n in names], chunksize=16), 1):
            if r:
                res[str(r[0])] = r[1]
            if i % 4000 == 0:
                print(f'  {i}/{len(names)} 残した {len(res)}  {time.time() - t0:.0f}秒', flush=True)
    meta = {'generated': time.strftime('%Y-%m-%d'), 'tool': 'night/moat_repl_posthoc.py --build（事後・D1）',
            'note': 'その時点の数字の主系列＝年 Y を持つ候補（moat_track_panel の表は年数の多い候補）。今日の数字は同じ',
            'vintages': list(VINT_ALL), 'cutoffs': MTP.CUT, 'fwd_lo': MTP.FWD_LO, 'n': len(res)}
    with open(PANEL_V, 'w') as f:
        json.dump({'meta': meta, 'firms': res}, f, separators=(',', ':'))
    print(f'書いた {PANEL_V}  {len(res)}社  {time.time() - t0:.0f}秒')


def holes(pan):
    out = {}
    for Y in VINT_ALL:
        g = gb = 0
        for f in pan['firms'].values():
            r = (f['pit'].get(str(Y)) or {}).get(str(Y))
            if r is None or r[1] is None or r[0] is not None:
                continue
            g += 1
            lr = f['latest'].get(str(Y))
            if lr and lr[0] and lr[0] >= 200e6:
                gb += 1
        out[str(Y)] = {'営業利益あり・売上なし': g, 'うち今日の売上2億ドル以上': gb}
    return out


def r3(v):
    return None if v is None else round(float(v), 3)


def prim_B(V, U):
    """主の判定と同じ計算（ビンテージ 2019・同じ種・同じ規則）＋各ビンテージの ρ"""
    P = {y: {o: T.pct_of(V[y], U[y][o], e, f)[0] for o, (e, f, _) in R.OUT_B.items() if o in ('O3m', 'O3t')} for y in R.VINT_B}
    rec, pv = {}, {}
    for i, (k, o, sg) in enumerate(R.PRIM_B):
        row = {}
        for y in R.VINT_B:
            ks = [c for c in P[y][o] if V[y][c].get(k) is not None]
            row[str(y)] = {'n': len(ks), 'rho': r3(MP.spear([V[y][c][k] for c in ks], [P[y][o][c] for c in ks]))}
        Y = R.PRIMARY_B
        ks = [c for c in P[Y][o] if V[Y][c].get(k) is not None]
        r, p1, p2 = R.rho_p1([V[Y][c][k] for c in ks], [P[Y][o][c] for c in ks], R.SEED + 40000 + i, sg)
        pv[f'{k}|{o}'] = p1
        rec[f'{k}|{o}'] = {'n': len(ks), 'rho': r3(r), 'p_片側': round(p1, 4), 'ビンテージごと': row, 'sg': sg}
    adj = MP.holm(pv)
    for key, x in rec.items():
        sg = x.pop('sg')
        x['p_Holm'] = round(adj[key], 4)
        c1 = sg * x['rho'] >= R.FLOOR_B and adj[key] < 0.05
        c2 = all(sg * (x['ビンテージごと'][y]['rho'] or 0) > 0 for y in ('2017', '2018'))
        x['事前登録の規則に当てると'] = '再現の条件を満たす' if (c1 and c2) else '満たさない'
    return rec


def prim_A(R18):
    out = {}
    for i, (k, o, sg) in enumerate(R.PRIM_A):
        e, f = R.OUT_A[o][:2]
        tk = [t for t, d in R18.items() if d[e] is not None and d[f] is not None]
        pct = T.pct_of(R18, tk, e, f)[0]
        ks = [t for t in pct if R18[t].get(k) is not None]
        r, p1, _p2 = R.rho_p1([R18[t][k] for t in ks], [pct[t] for t in ks], R.SEED + i, sg)
        out[f'{k}|{o}'] = {'n': len(ks), 'rho': r3(r), 'p_片側（Holm 前）': round(p1, 4)}
    return out


def resid(y, X):
    """y（順位）を X の列（順位から作った説明変数）で最小二乗回帰した残差"""
    A = np.column_stack([np.ones(len(y))] + [np.asarray(x, float) for x in X])
    b, *_ = np.linalg.lstsq(A, np.asarray(y, float), rcond=None)
    return np.asarray(y, float) - A @ b


def anchor_rows(rows, keys, comp, e, f, m, seed):
    """rows[c]: 入口 e・前方 f・直近の年 m・部品 comp。直近の年がそろう社だけで、4つの驚きで部品の ρ を並べる"""
    tk = [c for c in keys if rows[c].get(e) is not None and rows[c].get(f) is not None and rows[c].get(m) is not None]
    if len(tk) < 30:
        return {'n': len(tk), 'note': 'n<30'}
    ex = T.rankavg([rows[c][e] for c in tk])
    fy = T.rankavg([rows[c][f] for c in tk])
    my = T.rankavg([rows[c][m] for c in tk])
    exs = (ex - ex.mean()) / ex.std()
    S0 = resid(fy, [ex])                                  # 事前登録と同じ驚き（同じ社の集合の中で）
    S1 = resid(fy, [ex, my])                              # 錨に直近の年の水準を足す
    S3 = resid(fy, [exs, exs ** 2, exs ** 3])             # 錨を入口の3次式に
    idx = [i for i, c in enumerate(tk) if rows[c].get(comp) is not None]
    x = [rows[tk[i]][comp] for i in idx]
    dev = [rows[tk[i]][m] - rows[tk[i]][e] for i in idx]
    out = {'n': len(idx)}
    for name, Sx, sd in (('事前登録の驚き（同じ社）', S0, 0), ('錨＋直近の年の水準', S1, 1), ('錨を入口の3次式', S3, 3)):
        r, _p1, p2 = R.rho_p1(x, [float(Sx[i]) for i in idx], seed + sd, +1)
        out[name] = {'rho': r3(r), 'p_両側': None if p2 is None else round(p2, 4)}
    out['直近の年の偏り（年Yの値−入口の中央値）を除いた偏順位相関'] = r3(MP.partial(x, [float(S0[i]) for i in idx], dev))
    out['部品と直近の年の偏りの順位相関'] = r3(MP.spear(x, dev))
    return out


def main():
    if '--build' in sys.argv:
        build_variant()
        return
    pan = R.load_panel()
    res = {'generated': datetime.date.today().isoformat(), 'tool': 'night/moat_repl_posthoc.py',
           '位置づけ': '事後の診断（moat_repl の結果を見た後に足した）。判定は out/moat_repl.json のまま動かさない',
           '置換の回数': R.NPERM}
    # ── D2: 直近の年の水準（元の表） ──
    V, sic = R.build(pan, fetch_sic=True)
    F = pan['firms']
    for y in sorted(V):
        for c, d in V[y].items():
            row = (F[c]['pit'].get(str(y)) or {}).get(str(y)) or [None] * 6
            d['m_opm'], d['m_rt'] = row[T.I_OPM], row[T.I_RT]
    U = R.universes_B(V, sic)
    d2 = {}
    for i, (k, o, sg) in enumerate(R.PRIM_B):
        e, f = R.OUT_B[o][:2]
        m = 'm_opm' if o == 'O3m' else 'm_rt'
        d2[f'{k}|{o}（向き {"+" if sg > 0 else "−"}）'] = {str(y): anchor_rows(V[y], U[y][o], k, e, f, m, R.SEED + 90000 + 100 * i + 10 * (y - 2016))
                                                         for y in R.VINT_B}
    R18 = R.reads_2018(V)
    for j, k in enumerate(('moat5', 'irr', 'M4', 'M3')):
        d2[f"A' {k}|O2m（2018年の読解の社）"] = anchor_rows(R18, list(R18), k, 'e_opm', 'f_opm2', 'm_opm', R.SEED + 95000 + 10 * j)
        d2[f"A' {k}|O3m（2018年の読解の社）"] = anchor_rows(R18, list(R18), k, 'e_opm', 'f_opm1', 'm_opm', R.SEED + 96000 + 10 * j)
    res['D2 直近の年の水準（元の表）'] = d2
    # ── D1: 売上の穴（主系列を年 Y を持つ候補にした表） ──
    d1 = {'穴の数（元の表）': holes(pan)}
    if os.path.exists(PANEL_V):
        pv = json.load(open(PANEL_V))
        d1['穴の数（年 Y を持つ候補を主にした表）'] = holes(pv)
        V2, sic2 = R.build(pv, fetch_sic=True)
        U2 = R.universes_B(V2, sic2)
        d1['母集団（2019）'] = {'元の表': {o: len(U[2019][o]) for o in ('O3m', 'O3t')},
                             '直した表': {o: len(U2[2019][o]) for o in ('O3m', 'O3t')}}
        d1["B' 主の判定と同じ計算（元の表）"] = prim_B(V, U)
        d1["B' 主の判定と同じ計算（直した表）"] = prim_B(V2, U2)
        d1["A' 主の2本（元の表）"] = prim_A(R18)
        d1["A' 主の2本（直した表）"] = prim_A(R.reads_2018(V2))
    else:
        d1['note'] = '直した表が無い（--build で作る）'
    res['D1 売上の穴'] = d1
    with open(OUTF, 'w', encoding='utf-8') as fo:
        json.dump(res, fo, ensure_ascii=False, indent=1)
    print('書いた', OUTF)


if __name__ == '__main__':
    main()
