#!/usr/bin/env python3
"""night/moat_era90_test.py — 堀の部品を1990年代の入口で測り、10〜14年先と20〜24年先の持続を見る（2026-10-12新設・読むだけ）

決断待ち moat_redesign_1011 の続き（①moat_persist・②moat_track・再現 moat_repl・深掘り moat_deep のあと）。
ユーザー「もっと深く調べられない？まだ歴史検証ならやる余地はあるのでは？」。これまでの検定の入口はどれも XBRL の時代
（2007〜2020年）だった。ここでは XBRL より前の決算の原本（10-K に付いた EX-27 Financial Data Schedule・Article 5・
1995〜1999年度）を入口にし、同じ部品（粗利率の水準・利益率の安定・資本コストを上回った年の割合・シェアの趨勢）が
10〜14年先（2009〜2013年度）と20〜24年先（2019〜2023年度）の利益率と資本利益率の持続を当てるかを、事前登録どおり一度だけ裁く。
入口と前方の時代が重ならない＝moat_track・moat_repl・moat_deep とは独立の標本。前方は今日の companyfacts（XBRL）から、
入口の全社について取り直す（moat_track の表は売上2億ドル以上の社だけなので使わない＝後の大きさで社を選ぶことになる）。
門の採点・刻み・重み・関門・売却規律には触れない（絶対のルール1）。

材料: out/_mw_cache/ex27/parsed_v2.jsonl.gz（night/mw_ex27.py crawl → parse_all・gitignore）と companyfacts.zip。
使い方: python3 night/moat_era90_test.py --build（入口と前方の表 out/_era90_panel.json・gitignore）
        python3 night/moat_era90_test.py --count（数と自己検問だけ・前方の値は数えない）
        python3 night/moat_era90_test.py --smoke（前方を乱数にして道具が動くかだけ）
        引数なし（本番・一度だけ・事前登録 out/moat_era90_prereg.json が要る）
"""
import datetime, json, multiprocessing as mp, os, statistics as S, sys, time, zipfile

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import mw_ex27 as X                      # noqa: E402
import backtest_core as BC               # noqa: E402
import moat_track_panel as MTP           # noqa: E402
import retro_growth_persistence as RGP   # noqa: E402
import moat_track_test as T              # noqa: E402
import moat_repl_test as R               # noqa: E402
import moat_persist_test as MP           # noqa: E402

OUT = os.path.join(BASE, 'out')
PANEL = os.path.join(OUT, '_era90_panel.json')
PRE = os.path.join(OUT, 'moat_era90_prereg.json')
RES = os.path.join(OUT, 'moat_era90.json')
Y = 1999                                  # 入口の最後の年度（期末の暦年・早い1月の52/53週は前年＝mw_ex27.fy_label）
ENTRY = range(1995, 2000)
CUT = '2000-07-01'                        # 入口に使う提出の締め日（その時点で読めた数字）
MIN_REV = 150e6                           # 1999年度の売上（≈ 2012年のドルで2億ドル＝moat_track の下限の物価分）
W10, W20 = range(2009, 2014), range(2019, 2024)
FWD_LO = 2007                             # 前方の候補のタグは2007年以降の年だけで継ぐ（moat_track と同じ理由）
TAX = 0.79
HURDLE, HIGH = 0.09, 0.15
FLOOR = 0.10
NPERM = 4000
SEED = 20261014
PRE_TAGS = BC.TAGS['pre']
SBC_TAGS = ['ShareBasedCompensation', 'AllocatedShareBasedCompensationExpense']   # 株式報酬（2006年の会計基準の変更より前は多くが費用でなかった）
INT_TAGS = ['InterestExpense', 'InterestAndDebtExpense', 'InterestExpenseNonoperating', 'InterestExpenseDebt']
LTD_TAGS = ['LongTermDebtNoncurrent', 'LongTermDebt']
EQ_TAGS = MTP.EQ_TAGS


# ── 入口（EX-27） ──
def _scale(r):
    """倍率の表記が欠けた表の桁を mw_ex27.ta_dollars（純利益≈1株利益×表紙の株数）で直す倍率。決まらなければ 1（表記どおり）"""
    fd = r['fds']
    ta = fd['v'].get('TOTAL-ASSETS')
    if not ta or ta <= 0 or (fd.get('mult') or 1.0) != 1.0:
        return 1.0
    td = X.ta_dollars(fd, r.get('cover') or {})
    return (td / ta) if td else 1.0


def ex27_year(v, sf):
    """EX-27 Article 5 の1年分 → {rev, gm, em, rg, ta}。売上＝TOTAL-REVENUES（無ければ SALES）。原価＝mw_ex27.cogs_rule。
       EBIT の代わり＝税引前利益＋支払利息（INTEREST-EXPENSE は表記どおりの符号・欠測は0）。資本＝COMMON＋OTHER-SE＋PREFERRED＋
       PREFERRED-MANDATORY＋BONDS（長期の借入）。ROIC（のれん込み）＝EBIT×0.79÷資本（資本>0）"""
    g = lambda t: v.get(t)
    rev = g('TOTAL-REVENUES')
    if rev is None or rev <= 0:
        rev = g('SALES') if (g('SALES') is not None and g('SALES') > 0) else None
    out = {'rev': None if rev is None else rev * sf, 'gm': None, 'em': None, 'rg': None, 'ta': None}
    ta = g('TOTAL-ASSETS')
    if ta is not None and ta > 0:
        out['ta'] = ta * sf
    if rev is None:
        return out
    cg, _how = X.cogs_rule(v, rev)
    if cg is not None:
        x = (rev - cg) / rev
        out['gm'] = x if -1 <= x <= 1 else None
    pt = g('INCOME-PRETAX')
    if pt is not None:
        ebit = pt + (g('INTEREST-EXPENSE') or 0.0)
        x = ebit / rev
        out['em'] = x if -1 <= x <= 1 else None
        if g('COMMON') is not None or g('OTHER-SE') is not None:
            eq = sum(g(t) or 0.0 for t in ('COMMON', 'OTHER-SE', 'PREFERRED', 'PREFERRED-MANDATORY'))
            cap = eq + (g('BONDS') or 0.0)
            if cap > 0:
                out['rg'] = ebit * TAX / cap
    return out


def entry_panel():
    """CIK → {name, sic, years: {fy: {...}}}。提出日が CUT 以前の 10-K の EX-27（Article 5・12か月）だけ。同じ年度は最後に提出された表。
       自分の年度の表が無い年は、翌年度の提出に載る前年の表（同じ締め日以前に提出されたもの）で埋める"""
    panel, _recs = X.build_panel_ex27()
    out = {}
    for cik, fil in panel.items():
        yrs, fill, sic, name = {}, {}, None, None
        for r in fil:
            if r['filed'] > CUT or not r.get('fds') or r['fds'].get('article') != '5':
                continue
            fy = r['fy']
            sf = _scale(r)
            yrs[fy] = (r['filed'], ex27_year(r['fds']['v'], sf), r.get('sic'), r['name'])
            pv = r.get('fds_prev_restated')
            if pv and pv.get('article') == '5' and pv.get('pend'):
                fill[X.fy_label(pv['pend'])] = (r['filed'], ex27_year(pv['v'], sf))
        if not yrs:
            continue
        for fy, (fd_, row) in fill.items():
            if fy not in yrs:
                yrs[fy] = (fd_, row, None, None)
        last = max(yrs)
        sic = next((yrs[k][2] for k in sorted(yrs, reverse=True) if yrs[k][2]), None)
        name = yrs[last][3] or next((yrs[k][3] for k in yrs if yrs[k][3]), None)
        out[cik] = {'name': name, 'sic': sic, 'years': {str(k): v[1] for k, v in yrs.items()}}
    return out


# ── 前方（今日の companyfacts） ──
_Z = None


def _init():
    global _Z
    _Z = zipfile.ZipFile(MTP.ZIP)


def _alt(j, tags, ymin):
    """候補＝代替: 年ごとに優先順の最初にある値"""
    out = {}
    for t in tags:
        for y, v in BC.annual_rows(j, t, None).items():
            if y >= ymin and y not in out:
                out[y] = v
    return out


def fwd_one(cik):
    try:
        j = json.loads(_Z.read(f'CIK{int(cik):010d}.json'))
    except Exception:
        return cik, None
    if not (j.get('facts') or {}).get('us-gaap'):
        return cik, None
    rev = MTP.merged(j, RGP.REV_TAGS, None, FWD_LO)
    pre = _alt(j, PRE_TAGS, FWD_LO)
    itr = _alt(j, INT_TAGS, FWD_LO)
    op = {y: v for y, v in BC.annual_rows(j, 'OperatingIncomeLoss', None).items() if y >= FWD_LO}
    eq = MTP.merged(j, EQ_TAGS, None, FWD_LO)
    ltd = _alt(j, LTD_TAGS, FWD_LO)
    sbc = _alt(j, SBC_TAGS, FWD_LO)
    rows = {}
    for y in range(FWD_LO, 2026):
        rv = rev.get(y)
        r = {'rev': rv, 'em': None, 'em0': None, 'opm': None, 'rg': None, 'rg0': None}
        if rv is not None and rv > 0:
            if y in pre:
                ebit0 = pre[y] + itr.get(y, 0.0)
                ebit = ebit0 + max(sbc.get(y, 0.0), 0.0)     # 主: 株式報酬を足し戻す（入口の1990年代の会計にそろえる）
                for key, eb in (('em', ebit), ('em0', ebit0)):
                    x = eb / rv
                    r[key] = x if -1 <= x <= 1 else None
                if y in eq:
                    cap = eq[y] + ltd.get(y, 0.0)
                    if cap > 0:
                        r['rg'] = ebit * TAX / cap
                        r['rg0'] = ebit0 * TAX / cap
            if y in op:
                x = op[y] / rv
                r['opm'] = x if -1 <= x <= 1 else None
        if any(v is not None for v in r.values()):
            rows[str(y)] = r
    return cik, {'name': j.get('entityName'), 'rows': rows}


def build():
    t0 = time.time()
    E = entry_panel()
    print(f'入口 {len(E)}社（EX-27・{time.time() - t0:.0f}秒）', flush=True)
    names = set(zipfile.ZipFile(MTP.ZIP).namelist())
    ciks = [c for c in E if f'CIK{int(c):010d}.json' in names]
    F = {}
    with mp.Pool(4, initializer=_init) as pool:
        for i, (c, r) in enumerate(pool.imap_unordered(fwd_one, ciks, chunksize=16), 1):
            if r:
                F[c] = r
            if i % 2000 == 0:
                print(f'  前方 {i}/{len(ciks)}  {time.time() - t0:.0f}秒', flush=True)
    meta = {'generated': time.strftime('%Y-%m-%d'), 'tool': 'night/moat_era90_test.py --build', 'cut': CUT,
            'n_entry': len(E), 'n_in_zip': len(ciks), 'n_fwd': len(F), 'zip_bytes': os.path.getsize(MTP.ZIP),
            'zip_mtime': time.strftime('%Y-%m-%d', time.localtime(os.path.getmtime(MTP.ZIP))),
            'ex27_parsed': X.PARSED, 'ex27_parsed_bytes': os.path.getsize(X.PARSED)}
    with open(PANEL, 'w') as f:
        json.dump({'meta': meta, 'entry': E, 'fwd': F}, f, separators=(',', ':'))
    print(f'書いた {PANEL}  入口 {len(E)}・前方 {len(F)}  {time.time() - t0:.0f}秒')


# ── 社ごとの行 ──
def med(v, need):
    v = [x for x in v if x is not None]
    return S.median(v) if len(v) >= need else None


def cvneg(v):
    v = [x for x in v if x is not None]
    if len(v) < 4:
        return None
    m = sum(v) / len(v)
    return None if m <= 0 else -S.pstdev(v) / m


def rows(pan):
    E, F = pan['entry'], pan['fwd']
    V = {}
    for c, e in E.items():
        ys = e['years']
        g = lambda y, k: (ys.get(str(y)) or {}).get(k)
        d = {'name': e['name'], 'sic': e['sic'], 'rev': g(Y, 'rev')}
        em = [g(y, 'em') for y in ENTRY]
        rg = [g(y, 'rg') for y in ENTRY]
        gm = [g(y, 'gm') for y in ENTRY]
        d['e_m'], d['e_g'] = med(em, 4), med(rg, 4)
        d['m_m'], d['m_g'] = g(Y, 'em'), g(Y, 'rg')
        rgv = [x for x in rg if x is not None]
        d['M1'] = (sum(1 for x in rgv if x >= HURDLE) / len(rgv)) if len(rgv) >= 4 else None
        d['M3'] = med(gm, 3)
        pri = [x for x in gm[:-1] if x is not None]
        d['M4'] = (g(Y, 'gm') - max(pri)) if (g(Y, 'gm') is not None and len(pri) >= 2) else None
        r0, r1 = g(Y - 4, 'rev'), g(Y, 'rev')
        d['g4'] = (r1 / r0) ** 0.25 - 1 if (r0 and r1 and r0 > 0 and r1 > 0) else None
        d['R1'], d['R2'], d['R3'] = cvneg(rg), cvneg(em), d['g4']
        fr = (F.get(c) or {}).get('rows') or {}
        h = lambda y, k: (fr.get(str(y)) or {}).get(k)
        for tag, W in (('10', W10), ('20', W20)):
            d['f_m' + tag] = med([h(y, 'em') for y in W], 3)
            d['f_g' + tag] = med([h(y, 'rg') for y in W], 3)
            d['f_n' + tag] = med([h(y, 'em0') for y in W], 3)      # 副: 株式報酬を足し戻さない
            d['f_r' + tag] = med([h(y, 'rg0') for y in W], 3)
            d['f_o' + tag] = med([h(y, 'opm') for y in W], 3)
            d['alive' + tag] = int(any(h(y, 'rev') is not None for y in W))
        V[c] = d
    return V


def universe(V):
    return [c for c, d in V.items() if d['rev'] is not None and d['rev'] >= MIN_REV and d['sic'] and len(d['sic']) >= 2
            and not d['sic'].startswith('6') and d['e_m'] is not None]


def share_trend(V, U):
    g3, g2 = {}, {}
    for c in U:
        d, s = V[c], V[c]['sic']
        if d['g4'] is None or len(s) < 3:
            continue
        g3.setdefault(s[:3], []).append(d['g4'])
        g2.setdefault(s[:2], []).append(d['g4'])
    for c in V:
        V[c]['M5'] = None
    for c in U:
        d, s = V[c], V[c]['sic']
        if d['g4'] is None or len(s) < 3:
            continue
        gm = S.median(g3[s[:3]]) if len(g3.get(s[:3], [])) >= 5 else (S.median(g2[s[:2]]) if len(g2.get(s[:2], [])) >= 5 else None)
        d['M5'] = None if gm is None else ((1 + d['g4']) / (1 + gm)) ** 4 - 1


# ── 統計 ──
def resid(y, X_):
    A = np.column_stack([np.ones(len(y))] + [np.asarray(x, float) for x in X_])
    b, *_ = np.linalg.lstsq(A, np.asarray(y, float), rcond=None)
    return np.asarray(y, float) - A @ b


def surprise2(V, keys, e, m, f):
    tk = [k for k in keys if V[k].get(e) is not None and V[k].get(m) is not None and V[k].get(f) is not None]
    if len(tk) < 20:
        return {}
    res = resid(T.rankavg([V[k][f] for k in tk]), [T.rankavg([V[k][e] for k in tk]), T.rankavg([V[k][m] for k in tk])])
    rk = T.rankavg(res)
    return {k: float(rk[i] / len(tk)) for i, k in enumerate(tk)}


def surprise1(V, keys, e, f):
    return T.pct_of(V, keys, e, f)[0]


def perm_corr(x, y, seed, sign):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 30 or x.std() == 0 or y.std() == 0:
        return None, None, None
    x = (x - x.mean()) / x.std()
    y = (y - y.mean()) / y.std()
    n = len(x)
    obs = float(x @ y / n)
    rng = np.random.default_rng(seed)
    one = two = 0
    for _ in range(NPERM):
        r = float(x @ rng.permutation(y) / n)
        one += sign * r >= sign * obs - 1e-12
        two += abs(r) >= abs(obs) - 1e-12
    return obs, one / NPERM, two / NPERM


def r3(v):
    return None if v is None else round(float(v), 3)


def fade_pool(V, U, fkey):
    """入口の ROIC（のれん込み・中央値）≥15% で前方がある社。fade＝前方の中央値 < 9%"""
    return [(c, 1 if V[c][fkey] < HURDLE else 0) for c in U if V[c]['e_g'] is not None and V[c]['e_g'] >= HIGH
            and V[c][fkey] is not None and V[c]['m_g'] is not None]


def partial_fade(V, P, comp, seed, sign):
    rows_ = [(c, b) for c, b in P if V[c].get(comp) is not None]
    if len(rows_) < 30:
        return {'n': len(rows_), 'note': 'n<30'}
    x = T.rankavg([V[c][comp] for c, _ in rows_])
    yb = np.array([float(b) for _, b in rows_])
    Z = [T.rankavg([V[c]['e_g'] for c, _ in rows_]), T.rankavg([V[c]['m_g'] for c, _ in rows_])]
    r, p1, p2 = perm_corr(resid(x, Z), resid(yb, Z), seed, sign)
    return {'n': len(rows_), 'n_fade': int(yb.sum()), 'rho': r3(r), 'p_片側': None if p1 is None else round(p1, 4),
            'p_両側': None if p2 is None else round(p2, 4)}


OUTS = {'Om10': ('e_m', 'm_m', 'f_m10'), 'Og10': ('e_g', 'm_g', 'f_g10'), 'Om20': ('e_m', 'm_m', 'f_m20'), 'Og20': ('e_g', 'm_g', 'f_g20')}
PRIM_S = [('M3', 'Om10', +1), ('R2', 'Om10', +1), ('M1', 'Og10', +1), ('M5', 'Og10', -1), ('M3', 'Om20', +1), ('R2', 'Om20', +1)]
PRIM_F = [('R2', -1), ('M5', +1)]


def verdict(r, sign, adjp, p2=None):
    if r is None:
        return '測れない'
    if sign * r >= FLOOR and adjp < 0.05:
        return '支持'
    if -sign * r >= FLOOR and p2 is not None and p2 < 0.05:
        return '逆向き'
    why = []
    if not sign * r >= FLOOR:
        why.append(f'向きをそろえた ρ={sign * r:+.3f} が下限 +{FLOOR} に届かない')
    if not adjp < 0.05:
        why.append(f'Holm 調整の片側 p={adjp:.3f}')
    return '支持されず（' + '・'.join(why) + '）'


def counts(V, U):
    out = {'入口（EX-27 で年度がある社）': len(V), '母集団（1999年度の売上1.5億ドル以上・SIC6を除く・入口の利益率が4年以上）': len(U)}
    for k in ('M1', 'M3', 'M4', 'M5', 'R1', 'R2', 'R3'):
        out[k] = sum(1 for c in U if V[c].get(k) is not None)
    for tag in ('10', '20'):
        out[f'前方の提出がある社（{tag}）'] = sum(V[c]['alive' + tag] for c in U)
        for o in ('f_m', 'f_g'):
            out[f'{o}{tag} がそろう社'] = sum(1 for c in U if V[c][o + tag] is not None)
    out['fade の母集団（入口の ROIC のれん込み≥15%・前方 10 がある）'] = len(fade_pool(V, U, 'f_g10'))
    return out


KNOWN = {  # 自己検問 S1: 1999年度の売上（各社の当時の 10-K の数字・百万ドル）
    '789019': ('MICROSOFT FY1999（6月期）', 19747), '50863': ('INTEL 1999', 29389), '21344': ('COCA-COLA 1999', 19805),
    '200406': ('JOHNSON & JOHNSON 1999', 27471), '80424': ('PROCTER & GAMBLE FY1999（6月期）', 38125)}
KNOWN_F = {  # 自己検問 S2: 2012年度の売上（XBRL の今日の数字・百万ドル）
    '789019': ('MICROSOFT FY2012', 73723), '50863': ('INTEL 2012', 53341), '21344': ('COCA-COLA 2012', 48017)}


def selfcheck(pan):
    out, bad = {}, []
    for c, (nm, exp) in KNOWN.items():
        v = ((pan['entry'].get(c) or {}).get('years') or {}).get(str(Y), {}).get('rev')
        ok = v is not None and abs(v / 1e6 - exp) / exp <= 0.03
        out[nm] = {'表の値（百万ドル）': None if v is None else round(v / 1e6), '当時の数字': exp, '一致（±3%）': ok}
        if not ok:
            bad.append(nm)
    for c, (nm, exp) in KNOWN_F.items():
        v = (((pan['fwd'].get(c) or {}).get('rows') or {}).get('2012') or {}).get('rev')
        ok = v is not None and abs(v / 1e6 - exp) / exp <= 0.03
        out[nm] = {'表の値（百万ドル）': None if v is None else round(v / 1e6), '10-K の数字': exp, '一致（±3%）': ok}
        if not ok:
            bad.append(nm)
    if bad:
        raise SystemExit(f'✗ 自己検問の食い違い: {bad}  {json.dumps(out, ensure_ascii=False)}')
    return out


def main():
    pan = json.load(open(PANEL))
    V = rows(pan)
    U = universe(V)
    share_trend(V, U)
    if '--count' in sys.argv:
        print(json.dumps({'自己検問': selfcheck(pan), '数': counts(V, U), '材料': pan['meta']}, ensure_ascii=False, indent=1))
        return
    if '--smoke' in sys.argv:
        rng = np.random.default_rng(1)
        for d in V.values():
            for k in list(d):
                if k.startswith('f_') and d[k] is not None:
                    d[k] = float(rng.normal(0.1, 0.1))
    elif not os.path.exists(PRE):
        raise SystemExit('✗ 事前登録 out/moat_era90_prereg.json が無い（測る前にコミットすること）')
    sc = selfcheck(pan)
    S2_ = {o: surprise2(V, U, *v) for o, v in OUTS.items()}
    S1_ = {o: surprise1(V, U, v[0], v[2]) for o, v in OUTS.items()}
    prim = {}
    for i, (k, o, sg) in enumerate(PRIM_S):
        ks = [c for c in S2_[o] if V[c].get(k) is not None]
        r, p1, p2 = R.rho_p1([V[c][k] for c in ks], [S2_[o][c] for c in ks], SEED + i, sg) if len(ks) >= 30 else (None, None, None)
        prim[f'E|{k}|{o}'] = {'仮説': f'{k} → {o}（向き {"+" if sg > 0 else "−"}）', 'n': len(ks), 'rho': r3(r),
                             'p_片側': None if p1 is None else round(p1, 4), 'p_両側': None if p2 is None else round(p2, 4)}
    P10 = fade_pool(V, U, 'f_g10')
    for i, (k, sg) in enumerate(PRIM_F):
        rec = partial_fade(V, P10, k, SEED + 10 + i, sg)
        rec['仮説'] = f'{k} → 10〜14年先に資本コストを割る（入口の ROIC≥15%・向き {"+" if sg > 0 else "−"}・入口の中央値と1999年度の水準を除く偏相関）'
        prim[f'E|{k}|fade10'] = rec
    sgn = {f'E|{k}|{o}': s for k, o, s in PRIM_S}
    sgn.update({f'E|{k}|fade10': s for k, s in PRIM_F})
    pv = {k: v['p_片側'] for k, v in prim.items() if v.get('p_片側') is not None}
    adj = MP.holm(pv)
    for k, v in prim.items():
        if k in adj:
            v['p_Holm'] = round(adj[k], 4)
            v['判定'] = verdict(v.get('rho'), sgn[k], adj[k], v.get('p_両側'))
        else:
            v['判定'] = '測れない'
    # 副（判定に使わない）
    sec = {'部品×目的変数（錨＝中央値と1999年度・ρ・両側 p）': {}, '部品×目的変数（錨＝中央値だけ）': {}}
    for j, k in enumerate(('M1', 'M3', 'M4', 'M5', 'R1', 'R2', 'R3')):
        for which, Sx, lab in ((2, S2_, '部品×目的変数（錨＝中央値と1999年度・ρ・両側 p）'), (1, S1_, '部品×目的変数（錨＝中央値だけ）')):
            row_ = {}
            for q, o in enumerate(OUTS):
                ks = [c for c in Sx[o] if V[c].get(k) is not None]
                r, _p1, p2 = R.rho_p1([V[c][k] for c in ks], [Sx[o][c] for c in ks], SEED + 100 + 20 * j + 5 * which + q, +1) if len(ks) >= 30 else (None, None, None)
                row_[o] = {'n': len(ks), 'rho': r3(r), 'p_両側': None if p2 is None else round(p2, 4)}
            sec[lab][k] = row_
    # 営業利益（OperatingIncomeLoss）で前方を測った場合（入口は税引前＋利息のまま）
    so = {}
    for tag in ('10', '20'):
        Sx = surprise2(V, U, 'e_m', 'm_m', 'f_o' + tag)
        so[tag] = {}
        for j, k in enumerate(('M1', 'M3', 'M5', 'R2')):
            ks = [c for c in Sx if V[c].get(k) is not None]
            r, _p1, p2 = R.rho_p1([V[c][k] for c in ks], [Sx[c] for c in ks], SEED + 300 + 10 * j + (tag == '20'), +1) if len(ks) >= 30 else (None, None, None)
            so[tag][k] = {'n': len(ks), 'rho': r3(r), 'p_両側': None if p2 is None else round(p2, 4)}
    sec['前方を営業利益率で（錨は入口の税引前＋利息の利益率）'] = so
    sn = {}
    for tag in ('10', '20'):
        for o, (e, m, f) in (('m', ('e_m', 'm_m', 'f_n' + tag)), ('g', ('e_g', 'm_g', 'f_r' + tag))):
            Sx = surprise2(V, U, e, m, f)
            for j, k in enumerate(('M1', 'M3', 'M5', 'R2')):
                ks = [c for c in Sx if V[c].get(k) is not None]
                r, _p1, p2 = R.rho_p1([V[c][k] for c in ks], [Sx[c] for c in ks], SEED + 350 + 10 * j + (tag == '20') * 2 + (o == 'g'), +1) if len(ks) >= 30 else (None, None, None)
                sn[f'O{o}{tag}|{k}'] = {'n': len(ks), 'rho': r3(r), 'p_両側': None if p2 is None else round(p2, 4)}
    sec['前方の株式報酬を足し戻さない場合'] = sn
    P20 = fade_pool(V, U, 'f_g20')
    fd = {}
    for P, lab in ((P10, '10〜14年先'), (P20, '20〜24年先')):
        fd[lab] = {'n': len(P), 'fade': sum(b for _, b in P)}
        for j, k in enumerate(('M1', 'M3', 'M4', 'M5', 'R1', 'R2', 'R3')):
            fd[lab][k] = partial_fade(V, P, k, SEED + 400 + 10 * j + (lab == '20〜24年先'), +1)
    sec['fade（偏相関・向き +）'] = fd
    sv = {}
    for k in ('M1', 'M3', 'M5', 'R2', 'e_m', 'e_g', 'R3'):
        ks = sorted([c for c in U if V[c].get(k) is not None], key=lambda c: V[c][k])
        if len(ks) < 30:
            continue
        n = len(ks)
        sv[k] = {nm: {'n': len(sl), '10の提出あり': r3(sum(V[c]['alive10'] for c in sl) / len(sl)), '20の提出あり': r3(sum(V[c]['alive20'] for c in sl) / len(sl))}
                 for nm, sl in (('下1/3', ks[:n // 3]), ('中1/3', ks[n // 3:2 * n // 3]), ('上1/3', ks[2 * n // 3:]))}
    sec['生き残り（同じ CIK で前方の年度の提出がある割合・三分位）'] = sv
    res = {'generated': datetime.date.today().isoformat(), 'tool': 'night/moat_era90_test.py', '事前登録': 'out/moat_era90_prereg.json',
           '材料': pan['meta'], '自己検問': sc, '数': counts(V, U), '主の判定（Holm 8本）': prim, '副': sec}
    if '--smoke' in sys.argv:
        print('煙の検査', {k: v.get('n') for k, v in prim.items()})
        print('煙の検査 ok（前方は乱数・何も書いていない）')
        return
    with open(RES, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print('自己検問', sc)
    for k, v in prim.items():
        print(k, v.get('n'), v.get('rho'), v.get('p_片側'), v.get('p_Holm'), '→', v.get('判定'))
    print('書いた', RES)


if __name__ == '__main__':
    if '--build' in sys.argv:
        build()
        sys.exit(0)
    main()
