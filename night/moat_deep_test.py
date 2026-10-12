#!/usr/bin/env python3
"""night/moat_deep_test.py — 堀の歴史検証を深める（2026-10-12新設・読むだけ）: 破れ・長い持続・2020年の自然実験

決断待ち moat_redesign_1011 の続き（①moat_persist・②moat_track・再現 moat_repl）。ユーザー「もっと深く調べられない？
まだ歴史検証ならやる余地はあるのでは？」。今ある財務の表で、まだ測っていない3つの角度を事前登録して一度だけ裁く:
  C 破れ   : 入口で資本利益率（のれん・無形を除く）が15%以上の社が、1〜5年先に資本コスト（9%）を割ったか（左の裾＝「壊れない」）
  D 長い持続: 入口を2011年まで下げ（XBRL の最初の提出に載る2007〜2008年の数字）、10〜14年先（2021〜2025）の持続
  B 2020年 : 新型コロナの年の営業利益率の落ち込みを、2019年までの数字で見分けられたか（同じ業種の中の順位）
答え合わせの驚きは、moat_repl の事後の教訓どおり『入口の5年の中央値と直近の年の両方』を錨にする（主）。中央値だけは副。
表は moat_track_panel と同じ定義で、その時点の売上の主系列だけ『年 Y を持つ候補』にした版（moat_repl_posthoc.merged_pref・
2018年のタグ替えの穴を直した版）。今日の数字（前方）は ② と同じ（候補を2013年以降に絞って継ぐ）。
門の採点・刻み・重み・関門・売却規律には触れない（絶対のルール1）。
使い方: python3 night/moat_deep_test.py --build（表 out/_moat5_panel.json・gitignore・約1分）
        python3 night/moat_deep_test.py --count（数だけ）／ --smoke（答えを乱数にして道具が動くかだけ）／
        引数なし（本番・一度だけ・事前登録 out/moat_deep_prereg.json が要る）
"""
import datetime, json, multiprocessing as mp, os, statistics as S, sys, time, zipfile

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import moat_track_panel as MTP        # noqa: E402
import moat_track_test as T           # noqa: E402
import moat_persist_test as MP        # noqa: E402
import moat_repl_test as R            # noqa: E402
import moat_repl_posthoc as PH        # noqa: E402
import industry_trends as IT          # noqa: E402

OUT = os.path.join(BASE, 'out')
PANEL = os.path.join(OUT, '_moat5_panel.json')
PRE = os.path.join(OUT, 'moat_deep_prereg.json')
RES = os.path.join(OUT, 'moat_deep.json')
VINT = tuple(range(2011, 2021))
FWD_LO = 2013                     # 今日の数字の窓（② と同じ・広げた表でも変えない）
NPERM = 4000
SEED = 20261013
I_REV, I_OP, I_GM, I_OPM, I_RG, I_RT = range(6)
HURDLE = 0.09
HIGH_ROIC = 0.15
FLOOR = 0.10                      # 主の効果の下限（moat_track・moat_repl と同じ）


# ── 表 ──
def build():
    """moat_track_panel の work をそのまま使い、その時点の数字だけ主系列を『年 Y を持つ候補』に（PH.merged_pref）。
       ビンテージ 2011〜2020・今日の数字は 2013 年以降（② と同じ）"""
    MTP.merged = PH.merged_pref
    MTP.set_vint(VINT)
    MTP.FWD_LO = FWD_LO
    keep = MTP.read_ciks()[0] | MTP.read_ciks_2018()[0]
    names = [n for n in zipfile.ZipFile(MTP.ZIP).namelist() if n.startswith('CIK') and n.endswith('.json')]
    t0, res = time.time(), {}

    def _init():
        MTP._init(VINT)
        MTP.FWD_LO = FWD_LO
    with mp.Pool(4, initializer=_init) as pool:
        for i, r in enumerate(pool.imap_unordered(MTP.work, [(n, keep) for n in names], chunksize=16), 1):
            if r:
                res[str(r[0])] = r[1]
            if i % 4000 == 0:
                print(f'  {i}/{len(names)} 残した {len(res)}  {time.time() - t0:.0f}秒', flush=True)
    meta = {'generated': time.strftime('%Y-%m-%d'), 'tool': 'night/moat_deep_test.py --build',
            'note': 'moat_track_panel と同じ定義・その時点の売上等の主系列＝年 Y を持つ候補（moat_repl_posthoc.merged_pref）・今日の数字は2013年以降',
            'vintages': list(VINT), 'cutoffs': MTP.CUT, 'fwd_lo': FWD_LO, 'n': len(res),
            'zip_bytes': os.path.getsize(MTP.ZIP), 'zip_mtime': time.strftime('%Y-%m-%d', time.localtime(os.path.getmtime(MTP.ZIP)))}
    with open(PANEL, 'w') as f:
        json.dump({'meta': meta, 'firms': res}, f, separators=(',', ':'))
    print(f'書いた {PANEL}  {len(res)}社  {time.time() - t0:.0f}秒')


# ── 社×ビンテージの行 ──
def row(f, Y):
    d = R.firm_vintage_x(f, Y)
    P, L = f['pit'].get(str(Y)) or {}, f['latest']
    last = P.get(str(Y)) or [None] * 6
    d['m_opm'], d['m_rt'] = last[I_OPM], last[I_RT]
    w10 = range(Y + 10, Y + 15)
    d['f_opm10'] = T.med(T.win(L, w10, I_OPM, 3))
    d['f_rt10'] = T.med(T.win(L, w10, I_RT, 3))
    g = lambda y, i: (L.get(str(y)) or [None] * 6)[i]
    d['opm19L'], d['opm20L'] = g(2019, I_OPM), g(2020, I_OPM)
    rec = [x for x in (g(2021, I_OPM), g(2022, I_OPM)) if x is not None]
    d['opm2122L'] = S.median(rec) if len(rec) == 2 else None
    d['rt19L'], d['rt20L'] = g(2019, I_RT), g(2020, I_RT)
    return d


def build_rows(pan, fetch_sic=True):
    F = pan['firms']
    V = {y: {} for y in VINT}
    for c, f in F.items():
        for y in VINT:
            if str(y) in f['pit']:
                V[y][c] = row(f, y)
    need = sorted({int(c) for y in VINT for c, d in V[y].items() if d['rev'] is not None and d['rev'] >= T.MIN_REV})
    sic = {str(k): v for k, v in IT.sic_map(need, fetch=fetch_sic).items()}
    for y in VINT:
        U = {c: d for c, d in V[y].items() if T.in_universe(d, sic.get(c))}
        T.share_trend(U, sic)
        for d in V[y].values():
            d.setdefault('M5', None)
    return V, sic


def universe(V, sic, y):
    return [c for c, d in V[y].items() if T.in_universe(d, sic.get(c))]


# ── B の会計年度の終わり（パックの年＝期末の暦年なので、2020年の行がいつ終わる期間かを原本の期末日で確かめる） ──
FYE = os.path.join(OUT, '_moat5_fye.json')
B_Y = 2019
_ZF = None


def _fye_init():
    global _ZF
    _ZF = zipfile.ZipFile(MTP.ZIP)


def _fye_one(cik):
    """営業利益（OperatingIncomeLoss）の FY・10-K の行のうち期末が2020年のものを、backtest_core.annual_rows と同じ規則
       （300日未満は捨てる・同じ年に複数あれば最後に提出された行）で1つ選び、その期末日"""
    try:
        j = json.loads(_ZF.read(f'CIK{int(cik):010d}.json'))
    except Exception:
        return cik, None
    node = ((j.get('facts') or {}).get('us-gaap') or {}).get('OperatingIncomeLoss') or {}
    best = None
    for unit, rows in (node.get('units') or {}).items():
        if unit not in ('USD', 'USD/shares', 'shares'):
            continue
        for r in rows:
            if r.get('fp') != 'FY' or r.get('form') not in ('10-K', '10-K/A') or r.get('val') is None:
                continue
            end, st, filed = r.get('end') or '', r.get('start'), r.get('filed') or ''
            if end[:4] != '2020':
                continue
            if st:
                try:
                    if (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(st)).days < 300:
                        continue
                except Exception:
                    pass
            if best is None or filed > best[0]:
                best = (filed, end)
    return cik, (best[1] if best else None)


def fye_map(ciks):
    have = json.load(open(FYE)) if os.path.exists(FYE) else {}
    need = [c for c in ciks if c not in have]
    if need:
        with mp.Pool(4, initializer=_fye_init) as pool:
            for c, e in pool.imap_unordered(_fye_one, need, chunksize=16):
                have[c] = e
        with open(FYE, 'w') as f:
            json.dump(have, f)
    return {c: have.get(c) for c in ciks}


def b_universe(V, sic):
    return [c for c in universe(V, sic, B_Y) if V[B_Y][c]['opm19L'] is not None and V[B_Y][c]['opm20L'] is not None]


# ── 驚き ──
def resid(y, X):
    A = np.column_stack([np.ones(len(y))] + [np.asarray(x, float) for x in X])
    b, *_ = np.linalg.lstsq(A, np.asarray(y, float), rcond=None)
    return np.asarray(y, float) - A @ b


def surprise2(rows, keys, e, m, f):
    """主: 前方の順位を、入口の中央値と直近の年の順位で回帰した残差の、その母集団の中の順位の割合"""
    tk = [k for k in keys if rows[k].get(e) is not None and rows[k].get(m) is not None and rows[k].get(f) is not None]
    if len(tk) < 20:
        return {}
    res = resid(T.rankavg([rows[k][f] for k in tk]), [T.rankavg([rows[k][e] for k in tk]), T.rankavg([rows[k][m] for k in tk])])
    rk = T.rankavg(res)
    return {k: float(rk[i] / len(tk)) for i, k in enumerate(tk)}


def surprise1(rows, keys, e, f):
    """副: 中央値だけの錨（moat_repl までと同じ）"""
    return T.pct_of(rows, keys, e, f)[0]


def within_rank(vals, grp, minsize=5):
    g = {}
    for k, v in vals.items():
        s = grp.get(k)
        if s and v is not None:
            g.setdefault(s, []).append(k)
    out = {}
    for s, ks in g.items():
        if len(ks) < minsize:
            continue
        rk = T.rankavg([vals[k] for k in ks])
        for i, k in enumerate(ks):
            out[k] = float(rk[i] / len(ks))
    return out


# ── 母集団（社単位） ──
def pool_C(V, sic, horizon):
    """C: 入口のROIC（のれん・無形を除く・中央値）≥15%・前方がそろう社。社単位＝**最初に条件を満たしたビンテージで1回**（2011→2020）。
       ★最新のビンテージを先に取ると、後のビンテージで条件を満たさなくなった社（＝その後に落ちた社）だけが前のビンテージに
       集まる＝前のビンテージの前方の窓と重なる年の数字で社を選ぶことになる。最初のビンテージなら選ぶのに使うのはその年までの数字だけ。
       horizon 'a1'（+1〜+5・ビンテージ 2011〜2020）／'a2'（+6〜+10・2011〜2017）"""
    fkey, yrs = ('f_rt1', VINT) if horizon == 'a1' else ('f_rt2', tuple(y for y in VINT if y <= 2017))
    seen, out = set(), []
    for y in sorted(yrs):
        for c in universe(V, sic, y):
            if c in seen:
                continue
            d = V[y][c]
            if d['e_rt'] is None or d[fkey] is None or d['e_rt'] < HIGH_ROIC:
                continue
            seen.add(c)
            out.append((y, c, 1 if d[fkey] < HURDLE else 0))
    return out


D_MAIN, D_CHECK = 2012, 2011


def pool_D(V, sic, y=D_MAIN):
    """D: そのビンテージの母集団（社単位＝1ビンテージなので1社1回）。主 2012（前方 +10〜+14＝2022〜2025）・
       確かめ 2011（2021〜2025・別に計算する。社も窓も 2012 とほとんど重なる＝独立ではない）"""
    return list(universe(V, sic, y))


def counts(V, sic, fye):
    """数だけ（前方の数字・破れ・驚きは数えない）"""
    out = {}
    for h in ('a1', 'a2'):
        P = pool_C(V, sic, h)
        out[f'C_{h}'] = {'n': len(P), 'ビンテージ別（最初に条件を満たした年）': {str(y): sum(1 for p in P if p[0] == y) for y in VINT}}
        for k in ('M1', 'M3', 'M5', 'R2', 'M4'):
            out[f'C_{h}'][k] = sum(1 for y, c, _b in P if V[y][c].get(k) is not None and V[y][c]['m_rt'] is not None)
    for o, (e, m, f) in OUT_D.items():
        out[f'D_{o}'] = {}
        for y in (D_MAIN, D_CHECK):
            ks = [c for c in pool_D(V, sic, y) if V[y][c][e] is not None and V[y][c][m] is not None and V[y][c][f] is not None]
            out[f'D_{o}'][str(y)] = {'n': len(ks), **{k: sum(1 for c in ks if V[y][c].get(k) is not None) for k in ('M1', 'M3', 'M5')}}
    ok = b_universe(V, sic)
    mon = {}
    for c in ok:
        e = fye.get(c)
        mon[e[5:7] if e else '不明'] = mon.get(e[5:7] if e else '不明', 0) + 1
    dec = [c for c in ok if (fye.get(c) or '')[5:7] == '12']
    out['B'] = {'母集団（2019年と2020年の営業利益率がそろう）': len(ok), '2020年の会計年度の終わりの月': dict(sorted(mon.items())),
                '主（12月に終わる会計年度）': len(dec)}
    for k in ('M1', 'M2', 'M3', 'R2', 'M5'):
        out['B'][k] = sum(1 for c in dec if V[B_Y][c].get(k) is not None)
    return out


def r3(v):
    return None if v is None else round(float(v), 3)


# ── 統計 ──
def perm_corr(x, y, seed, sign=+1, strata=None):
    """x と y の相関（どちらも順位か残差）と置換の p（y をビンテージの中で入れ替える）。片側（sign の向き）と両側"""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 20 or x.std() == 0 or y.std() == 0:
        return None, None, None
    x = (x - x.mean()) / x.std()
    y = (y - y.mean()) / y.std()
    n = len(x)
    obs = float(x @ y / n)
    rng = np.random.default_rng(seed)
    groups = None
    if strata is not None:
        st = np.asarray(strata)
        groups = [np.where(st == s)[0] for s in np.unique(st)]
    one = two = 0
    yy = y.copy()
    for _ in range(NPERM):
        if groups is None:
            yy = rng.permutation(y)
        else:
            for g in groups:
                yy[g] = rng.permutation(y[g])
        r = float(x @ yy / n)
        if sign * r >= sign * obs - 1e-12:
            one += 1
        if abs(r) >= abs(obs) - 1e-12:
            two += 1
    return obs, one / NPERM, two / NPERM


def dummies(labels):
    u = sorted(set(labels))
    return [np.array([1.0 if l == v else 0.0 for l in labels]) for v in u[1:]]


def partial_breach(P, V, comp, seed, sign):
    """C の主: 破れ（0/1）と部品の順位の偏相関——入口のROICの中央値・直近の年のROIC（順位）とビンテージを除く。置換はビンテージの中"""
    rows = [(y, c, b) for y, c, b in P if V[y][c].get(comp) is not None and V[y][c]['m_rt'] is not None]
    if len(rows) < 30:
        return {'n': len(rows), 'note': 'n<30'}
    x = T.rankavg([V[y][c][comp] for y, c, _ in rows])
    yb = np.array([float(b) for *_, b in rows])
    Z = [T.rankavg([V[y][c]['e_rt'] for y, c, _ in rows]), T.rankavg([V[y][c]['m_rt'] for y, c, _ in rows])] + dummies([y for y, *_ in rows])
    rx, ry = resid(x, Z), resid(yb, Z)
    r, p1, p2 = perm_corr(rx, ry, seed, sign, strata=[y for y, *_ in rows])
    return {'n': len(rows), 'n_breach': int(yb.sum()), 'rho_partial': r3(r), 'p_片側': None if p1 is None else round(p1, 4),
            'p_両側': None if p2 is None else round(p2, 4)}


def terciles(P, V, comp):
    rows = [(V[y][c][comp], b) for y, c, b in P if V[y][c].get(comp) is not None]
    if len(rows) < 30:
        return None
    rows.sort(key=lambda t: t[0])
    k = len(rows)
    out = {}
    for name, sl in (('下1/3', rows[:k // 3]), ('中1/3', rows[k // 3:2 * k // 3]), ('上1/3', rows[2 * k // 3:])):
        out[name] = {'n': len(sl), '破れた割合': round(sum(b for _, b in sl) / len(sl), 3)}
    return out


def verdict(rec, sign, adjp, extra_ok=True):
    r, p2 = rec.get('rho'), rec.get('p_両側')
    if r is None:
        return rec.get('判定') or '測れない'
    if sign * r >= FLOOR and adjp < 0.05 and extra_ok:
        return '支持'
    if -sign * r >= FLOOR and p2 is not None and p2 < 0.05:
        return '逆向き'
    why = []
    if not sign * r >= FLOOR:
        why.append(f'向きをそろえた ρ={sign * r:+.3f} が下限 +{FLOOR} に届かない')
    if not adjp < 0.05:
        why.append(f'Holm 調整の片側 p={adjp:.3f}')
    if not extra_ok:
        why.append('確かめのビンテージ 2011 で向きが合わない')
    return '支持されず（' + '・'.join(why) + '）'


# ── 歴史の読解（moat_repl と同じ時点のそろえ方） ──
def readings():
    D = MP.load()
    _k, t2c = MTP.read_ciks()
    out = {}
    for ry, py in ((2013, 2012), (2015, 2014)):
        m = {}
        for t, p in D[ry].items():
            c = t2c.get(t)
            if c is not None:
                m[str(c)] = {k: p.get(k) for k in ('irr', 'rep', 'dur', 'moatW', 'moat5', 'moat_today')}
        out[ry] = (py, m)
    _k2, t2c2 = MTP.read_ciks_2018()
    m, seen = {}, set()
    for fn in ('retro_moat_2018.json', 'retro_moat_2018_rest.json'):
        d = json.load(open(os.path.join(OUT, fn)))
        for r in (d['rows'] if isinstance(d, dict) and 'rows' in d else d):
            t = r.get('t') or r.get('ticker')
            if not t or t in seen:
                continue
            seen.add(t)
            m[str(t2c2[t])] = {'irr': MP.num(r.get('irr18')), 'moat5': MP.num(r.get('moat5'))}
    out[2018] = (2017, m)
    return out


# ── C 破れ ──
PRIM_C = [('M3', -1), ('R2', -1), ('M5', +1)]


def part_C(V, sic, RD):
    res, prim = {}, {}
    P1, P2 = pool_C(V, sic, 'a1'), pool_C(V, sic, 'a2')
    res['母集団'] = {'a1（+1〜+5年）': {'n': len(P1), '破れ': sum(b for *_, b in P1)}, 'a2（+6〜+10年）': {'n': len(P2), '破れ': sum(b for *_, b in P2)}}
    for i, (k, sg) in enumerate(PRIM_C):
        rec = partial_breach(P1, V, k, SEED + i, sg)
        rec['仮説'] = f'{k} → 破れ（向き {"+" if sg > 0 else "−"}）'
        rec['rho'] = rec.get('rho_partial')
        prim[f'C|{k}'] = rec
    sec = {}
    for P, h in ((P1, 'a1'), (P2, 'a2')):
        sec[h] = {}
        for j, k in enumerate(('M1', 'M3', 'M4', 'M5', 'R1', 'R2', 'R3')):
            rr = [(V[y][c][k], b) for y, c, b in P if V[y][c].get(k) is not None]
            r, _p1, p2 = R.rho_p1([a for a, _ in rr], [float(b) for _, b in rr], SEED + 300 + 10 * j + (h == 'a2'), +1) if len(rr) >= 30 else (None, None, None)
            sec[h][k] = {'n': len(rr), 'rho_そのまま': r3(r), 'p_両側': None if p2 is None else round(p2, 4),
                         '偏相関（入口と直近のROIC・ビンテージを除く）': partial_breach(P, V, k, SEED + 400 + 10 * j + (h == 'a2'), +1),
                         '三分位の破れた割合': terciles(P, V, k)}
        m1 = [(V[y][c]['M1'], b) for y, c, b in P if V[y][c].get('M1') is not None]
        sec[h]['M1 の分布'] = {'M1=1（入口の全年で9%以上）': sum(1 for a, _ in m1 if a >= 1), 'M1<1': sum(1 for a, _ in m1 if a < 1),
                             '破れた割合 M1=1': r3(S.mean([b for a, b in m1 if a >= 1])) if any(a >= 1 for a, _ in m1) else None,
                             '破れた割合 M1<1': r3(S.mean([b for a, b in m1 if a < 1])) if any(a < 1 for a, _ in m1) else None}
    # 読解（社単位・古い読解を先に: 2013→2015→2018＝選ぶのにその年までの数字しか使わない。pool_C と同じ理由）
    rd, seen = [], set()
    for ry in (2013, 2015, 2018):
        py, m = RD[ry]
        for c, s in m.items():
            if c in seen or c not in V[py]:
                continue
            d = V[py][c]
            if not T.in_universe(d, sic.get(c)) or d['e_rt'] is None or d['f_rt1'] is None or d['e_rt'] < HIGH_ROIC:
                continue
            seen.add(c)
            rd.append((py, c, 1 if d['f_rt1'] < HURDLE else 0, s))
    sec['読解（+1〜+5年・社単位）'] = {'n': len(rd), '破れ': sum(b for _, _, b, _ in rd)}
    for j, k in enumerate(('irr', 'moat5', 'rep', 'dur', 'moat_today')):
        rr = [(s.get(k), b) for _, _, b, s in rd if s.get(k) is not None]
        if len(rr) < 30:
            sec['読解（+1〜+5年・社単位）'][k] = {'n': len(rr), 'note': 'n<30'}
            continue
        r, _p1, p2 = R.rho_p1([a for a, _ in rr], [float(b) for _, b in rr], SEED + 500 + j, +1)
        hi = [b for a, b in rr if a >= (4 if k == 'moat5' else 70)]
        lo = [b for a, b in rr if a < (4 if k == 'moat5' else 70)]
        sec['読解（+1〜+5年・社単位）'][k] = {'n': len(rr), 'rho_そのまま': r3(r), 'p_両側': round(p2, 4),
                                       '破れた割合（上の刻み / 下の刻み）': [r3(S.mean(hi)) if hi else None, r3(S.mean(lo)) if lo else None,
                                                             len(hi), len(lo)],
                                       '上の刻みの線': '4以上' if k == 'moat5' else '70以上'}
    res['副'] = sec
    return prim, res


# ── D 10〜14年の持続 ──
PRIM_D = [('M3', 'O10m', +1), ('M1', 'O10t', +1), ('M5', 'O10t', -1)]
OUT_D = {'O10m': ('e_opm', 'm_opm', 'f_opm10'), 'O10t': ('e_rt', 'm_rt', 'f_rt10')}


def part_D(V, sic, RD):
    S2_, S1_ = {}, {}
    for o, (e, m, f) in OUT_D.items():
        S2_[o], S1_[o] = {}, {}
        for y in (D_MAIN, D_CHECK):
            ks = pool_D(V, sic, y)
            S2_[o][y] = surprise2(V[y], ks, e, m, f)
            S1_[o][y] = surprise1(V[y], ks, e, f)

    def get(o, k, which, y):
        Sx = S2_ if which == 2 else S1_
        a, b = [], []
        for c, s in Sx[o][y].items():
            v = V[y][c].get(k)
            if v is not None:
                a.append(v)
                b.append(s)
        return a, b

    res = {'母集団': {o: {str(y): len(S2_[o][y]) for y in (D_MAIN, D_CHECK)} for o in OUT_D}}
    prim = {}
    for i, (k, o, sg) in enumerate(PRIM_D):
        a, b = get(o, k, 2, D_MAIN)
        r, p1, p2 = R.rho_p1(a, b, SEED + 10 + i, sg)
        a2, b2 = get(o, k, 2, D_CHECK)
        rc = MP.spear(a2, b2) if len(a2) >= 20 else None
        prim[f'D|{k}|{o}'] = {'仮説': f'{k} → {o}（向き {"+" if sg > 0 else "−"}）', 'n': len(a), 'rho': r3(r),
                              'p_片側': None if p1 is None else round(p1, 4), 'p_両側': None if p2 is None else round(p2, 4),
                              '確かめ（ビンテージ 2011・別に計算・独立ではない）': {'n': len(a2), 'rho': r3(rc)}}
    sec = {}
    for o in OUT_D:
        sec[o] = {}
        for j, k in enumerate(('M1', 'M3', 'M4', 'M5', 'R1', 'R2', 'R3')):
            row_ = {}
            for which in (2, 1):
                for y in (D_MAIN, D_CHECK):
                    a, b = get(o, k, which, y)
                    r, _p1, p2 = R.rho_p1(a, b, SEED + 600 + 20 * j + which + (o == 'O10t') * 5 + (y == D_CHECK) * 2, +1) if len(a) >= 30 else (None, None, None)
                    row_[('錨＝中央値と直近の年' if which == 2 else '錨＝中央値だけ') + f'・{y}'] = {'n': len(a), 'rho': r3(r), 'p_両側': None if p2 is None else round(p2, 4)}
            sec[o][k] = row_
    py, m = RD[2013]
    rsec = {}
    for o in OUT_D:
        rsec[o] = {}
        Sx = S2_[o][py]
        for j, k in enumerate(('irr', 'rep', 'dur', 'moatW', 'moat5', 'moat_today')):
            ks = [c for c in m if c in Sx and m[c].get(k) is not None]
            if len(ks) < 30:
                rsec[o][k] = {'n': len(ks), 'note': 'n<30'}
                continue
            r, _p1, p2 = R.rho_p1([m[c][k] for c in ks], [Sx[c] for c in ks], SEED + 700 + 10 * j + (o == 'O10t'), +1)
            rsec[o][k] = {'n': len(ks), 'rho': r3(r), 'p_両側': round(p2, 4)}
    sec['読解（2013年→ビンテージ 2012・+10〜+13年・錨＝中央値と直近の年）'] = rsec
    res['副'] = sec
    return prim, res


# ── B 2020年 ──
PRIM_B = [('M3', +1), ('R2', +1), ('M1', +1), ('M2', +1)]


def b_groups(cs):
    g2 = {c: (SIC_[c] or '')[:2] for c in cs}
    cnt = {}
    for c in cs:
        cnt[g2[c]] = cnt.get(g2[c], 0) + 1
    return [g2[c] if cnt[g2[c]] >= 5 else 'other' for c in cs]


def b_outcome(V, cs, fkey, base):
    """2020年の驚き: fkey の順位を、base（2019年）の順位と業種（SIC2・5社以上、ほかは1つにまとめる）で回帰した残差の順位の割合"""
    cs = [c for c in cs if V[B_Y][c].get(fkey) is not None and V[B_Y][c].get(base) is not None]
    if len(cs) < 30:
        return {}
    grp = b_groups(cs)
    rr = resid(T.rankavg([V[B_Y][c][fkey] for c in cs]), [T.rankavg([V[B_Y][c][base] for c in cs])] + dummies(grp))
    rk = T.rankavg(rr)
    return {c: float(rk[j] / len(cs)) for j, c in enumerate(cs)}


SIC_ = {}


def part_B(V, sic, RD, fye):
    global SIC_
    SIC_ = sic
    Y = B_Y
    allc = b_universe(V, sic)
    dec = [c for c in allc if (fye.get(c) or '')[5:7] == '12']
    O = b_outcome(V, dec, 'opm20L', 'opm19L')
    grp = b_groups([c for c in dec])
    res = {'母集団': {'2019年と2020年の営業利益率がそろう（会計年度の終わりを問わない）': len(allc),
                    '主: 2020年の会計年度が12月に終わる': len(dec),
                    '業種（SIC2・5社以上）': len({g for g in grp if g != 'other'}),
                    '5社未満の業種に入る社（まとめて1つの業種）': sum(1 for g in grp if g == 'other')}}
    prim = {}
    for i, (k, sg) in enumerate(PRIM_B):
        ks = [c for c in O if V[Y][c].get(k) is not None]
        r, p1, p2 = R.rho_p1([V[Y][c][k] for c in ks], [O[c] for c in ks], SEED + 20 + i, sg) if len(ks) >= 20 else (None, None, None)
        prim[f'B|{k}'] = {'仮説': f'{k} → 2020年の営業利益率の驚き（12月決算・2019年の水準と業種を除く・向き {"+" if sg > 0 else "−"}）', 'n': len(ks),
                          'rho': r3(r), 'p_片側': None if p1 is None else round(p1, 4), 'p_両側': None if p2 is None else round(p2, 4)}
    sec = {}
    outs = (('2020年の営業利益率（主と同じ・12月決算）', O, 0),
            ('2020年の営業利益率（会計年度の終わりを問わない）', b_outcome(V, allc, 'opm20L', 'opm19L'), 1),
            ('戻り（2021〜2022年の中央値・12月決算）', b_outcome(V, dec, 'opm2122L', 'opm19L'), 2),
            ('2020年のROIC（のれん・無形を除く・12月決算）', b_outcome(V, dec, 'rt20L', 'rt19L'), 3))
    for j, k in enumerate(('M1', 'M2', 'M3', 'M4', 'M5', 'R1', 'R2', 'R3', 'R4')):
        row_ = {}
        for name, Ox, s0 in outs:
            ks = [c for c in Ox if V[Y][c].get(k) is not None]
            r, _p1, p2 = R.rho_p1([V[Y][c][k] for c in ks], [Ox[c] for c in ks], SEED + 800 + 10 * j + s0, +1) if len(ks) >= 30 else (None, None, None)
            row_[name] = {'n': len(ks), 'rho': r3(r), 'p_両側': None if p2 is None else round(p2, 4)}
        dd = [c for c in dec if V[Y][c].get(k) is not None]
        row_['そのままの落ち幅（12月決算・業種も水準も除かない）'] = {'n': len(dd), 'rho': r3(MP.spear([V[Y][c][k] for c in dd], [V[Y][c]['opm20L'] - V[Y][c]['opm19L'] for c in dd]))}
        sec[k] = row_
    rsec = {}
    for ry in (2018, 2015):
        _py, m = RD[ry]
        for j, k in enumerate(('irr', 'moat5', 'rep', 'dur')):
            ks = [c for c in O if c in m and m[c].get(k) is not None]
            if len(ks) < 30:
                continue
            r, _p1, p2 = R.rho_p1([m[c][k] for c in ks], [O[c] for c in ks], SEED + 900 + 10 * j + (ry == 2015), +1)
            rsec[f'{ry}年の読解 {k}'] = {'n': len(ks), 'rho': r3(r), 'p_両側': round(p2, 4)}
    sec['読解（12月決算の母集団の中）'] = rsec
    res['副'] = sec
    return prim, res


def selfcheck(pan):
    """S1: 今日の数字が moat_repl の表（out/_moat3_panel.json）と全社で一致／S2: その時点の数字（2012〜2020）が
       事後の表（out/_moat3v_panel.json・同じ merged_pref）と全社で一致"""
    a = json.load(open(R.PANEL))['firms']
    b = json.load(open(PH.PANEL_V))['firms']
    F = pan['firms']
    bad1 = [k for k in F if k in a and F[k]['latest'] != a[k]['latest']]
    bad2 = [k for k in F if k in b and any(F[k]['pit'].get(str(y)) != b[k]['pit'].get(str(y)) for y in range(2012, 2021))]
    if bad1 or bad2:
        raise SystemExit(f'✗ 自己検問: S1 食い違い {len(bad1)}（例 {bad1[:5]}）／S2 食い違い {len(bad2)}（例 {bad2[:5]}）')
    return {'S1（今日の数字＝moat_repl の表）': {'共通の社': sum(1 for k in F if k in a), '食い違い': 0},
            'S2（2012〜2020 のその時点の数字＝事後の表）': {'共通の社': sum(1 for k in F if k in b), '食い違い': 0}}


def main():
    pan = json.load(open(PANEL))
    V, sic = build_rows(pan, fetch_sic=True)
    fye = fye_map(b_universe(V, sic))
    if '--count' in sys.argv:
        print(json.dumps(counts(V, sic, fye), ensure_ascii=False, indent=1))
        return
    if '--smoke' in sys.argv:
        # 煙の検査: 前方の数字（答え）を乱数に置き換えて道具が最後まで動くかだけを見る。本物の答えは見ない・何も書かない
        rng = np.random.default_rng(1)
        for y in VINT:
            for d in V[y].values():
                for k in ('f_rt1', 'f_rt2', 'f_opm10', 'f_rt10', 'opm20L', 'opm2122L', 'rt20L', 'f_opm1', 'f_opm2', 'f_rg2', 'f_opm48', 'f_rt48'):
                    if d.get(k) is not None:
                        d[k] = float(rng.normal(0.1, 0.1))
        RD = readings()
        for name, fn in (('C', lambda: part_C(V, sic, RD)), ('D', lambda: part_D(V, sic, RD)), ('B', lambda: part_B(V, sic, RD, fye))):
            pr, _r = fn()
            print('煙の検査', name, {k: v.get('n') for k, v in pr.items()})
        print('煙の検査 ok（答えは乱数・何も書いていない）')
        return
    if not os.path.exists(PRE):
        raise SystemExit('✗ 事前登録 out/moat_deep_prereg.json が無い（測る前にコミットすること）')
    sc = selfcheck(pan)
    RD = readings()
    pc, rc = part_C(V, sic, RD)
    pd_, rd_ = part_D(V, sic, RD)
    pb, rb = part_B(V, sic, RD, fye)
    prim = {**pc, **pd_, **pb}
    sgn = {f'C|{k}': s for k, s in PRIM_C}
    sgn.update({f'D|{k}|{o}': s for k, o, s in PRIM_D})
    sgn.update({f'B|{k}': s for k, s in PRIM_B})
    pv = {k: v['p_片側'] for k, v in prim.items() if v.get('p_片側') is not None}
    adj = MP.holm(pv)
    for k, v in prim.items():
        if k not in adj:
            v['判定'] = v.get('判定') or '測れない'
            continue
        v['p_Holm'] = round(adj[k], 4)
        extra = True
        if k.startswith('D|'):
            extra = sgn[k] * (v['確かめ（ビンテージ 2011・別に計算・独立ではない）']['rho'] or 0) > 0
        v['判定'] = verdict(v, sgn[k], adj[k], extra)
    res = {'generated': datetime.date.today().isoformat(), 'tool': 'night/moat_deep_test.py', '事前登録': 'out/moat_deep_prereg.json',
           '材料': pan['meta'], '自己検問': sc, '数': counts(V, sic, fye), '主の判定（Holm 10本）': prim,
           'C 破れ': rc, 'D 10〜14年の持続': rd_, 'B 2020年': rb}
    with open(RES, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print('自己検問', sc)
    for k, v in prim.items():
        print(k, v.get('n'), v.get('rho'), v.get('p_片側'), v.get('p_Holm'), v.get('確かめ（ビンテージ 2011・別に計算・独立ではない）'), '→', v.get('判定'))
    print('書いた', RES)


if __name__ == '__main__':
    if '--build' in sys.argv:
        build()
        sys.exit(0)
    main()
