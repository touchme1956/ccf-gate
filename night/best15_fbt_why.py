#!/usr/bin/env python3
"""night/best15_fbt_why.py — best15 の形で FBT が15%以上の確率を上げる理由を部品に分ける（2026-11-01・参考・判定なし・配分は変えない）

ユーザーの問い「なぜFBTだとあがるの？？」。best15（docs/CLAUDE_ARCHIVE.md:20903）の形で FBT を同じ比の XLV に替えた形と比べ、
差を4つの部品に Shapley で分ける（4部品の 16通りの組み合わせから出す・順番によらず、足すと差に一致する）:
  hist  歴史の世界（A1 直近26年・A2 直近15年の実績の年率）
  raw   未来の世界（B・C・D）の各本の予想の年率の重み付き（分散の上乗せの前）
  bonus 分散の上乗せ 0.5(w·s² − w'Σw)（B・C・D に足す・Σ は 2000-09〜2026-09 の月次）
  sig   積立の道の表に入れるぶれ σ＝√(w'Σw)（全部の世界で同じ）
物差しは night/unx_assets.measure（USD・崩れあり）と同じ式（best15_check.Fast と 1e-12 以内で一致することを確かめてから使う）。
形（問いから決まる・結果を見て変えていない）:
  ② SMH40/FBT30/ITA15/NASDAQ100 15（best15 の勧め＝D1 の注文書の形）
  ① SMH40/FBT25/NASDAQ100 20/GDX10/ITA5（決まりの答えを注文書の形に）
  今の XLV10 を FBT10 に（今＝QQQM50/SMH20/ITA20/XLV10）
併せて出す: 世界ごとの年率と15%以上・5%未満の確率／感度（分散の上乗せなし・A2を外す・未来の世界だけ・未来だけで上乗せなし・
  ndx_swap_check.variants の5本）／道の表の例（同じ年率でぶれだけ変える）／FBT と XLV の単体（年率・ぶれ・相関）・期間ごと・
  暦年の差・単体の最大下落／100年の代用（FBT＝French の医薬品 Drugs・XLV＝Drugs・MedEq・Hlth の時価加重＝unx_assets.century_parts）
  事後（判定に使わない）: ②・① の XLV 版を best15 の T1 の8つの物差しと最終の確かめ（感度5本・円の枠）で今と比べる
⚠ 下書き（scratchpad）で一度回してから道具にした（形と部品は問いから決まる）。部品の分け方は一つの見方。
追記（同日・ユーザー「100年の歴史検証は参考にされてないの？」）: 「長い記録」の節を足した（判定に使わない）——
  B の世界（100年の平均）の FBT と XLV の中身（費用の前の年率・業種の上乗せ・記録の業種・費用）／
  100年の写しの単体（1927〜・French の医薬品・医療機器・医療サービス・その時価加重・市場）の年率・ぶれ・最大下落・30年の積立／
  バイオ自体の一番長い実物の記録 FBIOX（Fidelity Select Biotechnology・1986-01〜・費用込み）と同じ期間の写しの比べ（20年の積立）／
  out/etf_longest.json（2026-09-25）の健康・バイオの本の行の写し
使い方: python3 night/best15_fbt_why.py → out/best15_fbt_why.json
"""
import contextlib, io, itertools, json, math, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'best15_fbt_why.json')

FORMS = {
    '②（勧め）SMH40/FBT30/ITA15/NASDAQ100 15': {'SMH': 40, 'FBT': 30, 'ITA': 15, 'QQQM': 15},
    '①（決まりの答えの注文書の形）SMH40/FBT25/NASDAQ100 20/GDX10/ITA5': {'SMH': 40, 'FBT': 25, 'QQQM': 20, 'GDX': 10, 'ITA': 5},
    '今の XLV10 を FBT10 に': {'QQQM': 50, 'SMH': 20, 'ITA': 20, 'FBT': 10},
}
FACT = ('hist', 'raw', 'bonus', 'sig')
FACT_JA = {'hist': '歴史の世界（A1・A2 の実績）', 'raw': '未来の世界の予想そのもの（B・C・D）', 'bonus': '分散の上乗せ', 'sig': 'ぶれ（道の表の σ）'}
POOL = ['QQQM', 'SMH', 'ITA', 'XLV', 'FBT', 'GDX', 'XLK', 'VOO']


def log(*a):
    print('[fbt_why]', *a, flush=True)


def swap(f, frm='FBT', to='XLV'):
    g = dict(f)
    v = g.pop(frm)
    g[to] = g.get(to, 0) + v
    return g


class Parts:
    """best15_check.Fast の配列をそのまま使い、世界の年率を部品に分けて組み直す"""

    def __init__(self, fast):
        self.f = fast
        self.P, self.E = fast.P, fast.E

    def vec(self, form):
        t = sum(form.values())
        return np.array([form.get(c, 0) / t for c in self.f.pool])

    def ingred(self, form):
        import etf_forward_combo as CB
        f, w = self.f, self.vec(form)
        geo, vol, mdd = CB.path_stats((w @ f.G1)[None, :], f.T1)
        wadj = float(w @ f.adj)
        a2 = float(np.expm1(np.log1p(w @ f.G2).sum() * 12 / f.T2))
        q = float(w @ f.S1 @ w)
        return dict(hist=dict(A1=float(geo[0]) + wadj, A2=a2 + wadj),
                    raw=dict(B=float(w @ f.lB), C=float(w @ f.lC), D=float(w @ f.lD)),
                    bonus=0.5 * (float(w @ f.s1) - q), sig=math.sqrt(q), vol=float(vol[0]), mdd=float(mdd[0]))

    @staticmethod
    def worlds(ing):
        wv = dict(ing['hist'])
        for k in ('B', 'C', 'D'):
            wv[k] = math.expm1(ing['raw'][k] + ing['bonus'])
        return wv

    def prob(self, m, sig, tau):
        v = float(self.P.interp(self.f.tabs[tau], np.array([m]), np.array([sig]))[0])
        return v if tau >= 0.10 else 1 - v

    def metric(self, ing, p=None, nobonus=False):
        p = p or self.f.pi
        if nobonus:
            ing = dict(ing, bonus=0.0)
        wv = self.worlds(ing)
        ks = [k for k in self.E.WORLDS if p.get(k, 0) > 0]
        den = sum(p[k] for k in ks)
        per15 = {k: self.prob(math.log1p(wv[k]), ing['sig'], 0.15) for k in ks}
        per5 = {k: self.prob(math.log1p(wv[k]), ing['sig'], 0.05) for k in ks}
        return dict(P15=sum(p[k] * per15[k] for k in ks) / den, P5=sum(p[k] * per5[k] for k in ks) / den,
                    mean=sum(p[k] * wv[k] for k in ks) / den, per15=per15, per5=per5, wv=wv)

    def shapley(self, base, alt, key, **kw):
        n = len(FACT)
        mix = lambda S: {k: (alt[k] if k in S else base[k]) for k in FACT}
        phi = {}
        for i in FACT:
            others = [x for x in FACT if x != i]
            s = 0.0
            for r in range(n):
                for S in itertools.combinations(others, r):
                    wt = math.factorial(r) * math.factorial(n - r - 1) / math.factorial(n)
                    s += wt * (self.metric(mix(set(S) | {i}), **kw)[key] - self.metric(mix(set(S)), **kw)[key])
            phi[i] = s
        return phi


def long_record(U, res, rows):
    """100年の写しとバイオの一番長い実物の記録（判定に使わない）"""
    import statistics as St
    C = U.century_parts()
    F, parts, mkt = C['F'], C['parts'], C['mkt']
    _, ret, _, _, _, _, _ = F.load()
    allm = sorted(mkt)
    fb = res['raw']['FBIOX']
    ser = {'医薬品 Drugs（FBT の100年の写し）': ret['Drugs'], '医療機器 MedEq': ret['MedEq'], '医療サービス Hlth': ret['Hlth'],
           '医薬品・医療機器・医療サービスの時価加重（XLV の100年の写し）': parts['XLV'], '市場（French の米国株全体）': mkt}

    def stats(s, ms):
        L = np.log1p(np.array([s[m] for m in ms]))
        w = np.exp(np.cumsum(L))
        peak, uw, best = -1.0, 0, 0
        for v in w:
            if v >= peak:
                peak, uw = v, 0
            else:
                uw += 1
                best = max(best, uw)
        return {'期間': f'{ms[0]}〜{ms[-1]}', '年率': pct(math.expm1(L.sum() * 12 / len(L))), 'ぶれ': pct(float(L.std() * math.sqrt(12)), 1),
                '最大下落': pct(float((w / np.maximum.accumulate(w) - 1).min()), 1), '高値を下回った最長（年）': round(best / 12, 1)}

    def dca(s, starts, n, end):
        v = []
        for y in starts:
            ms = F.months((y + 1) * 100 + 1, n)
            if ms[-1] > end or any(m not in s for m in ms):
                continue
            v.append(F.dca_mult(s, ms) / F.dca_mult(mkt, ms))
        v.sort()
        return {'窓': len(v), '中央': round(St.median(v), 3), '最悪': round(v[0], 3), '市場に勝った割合': round(sum(x > 1 for x in v) / len(v), 2)}

    out = {}
    out['B の世界（100年の平均）の中身'] = {c: {'費用の前の年率': pct(rows[c]['B_gross']), '業種の100年の上乗せ（半分にする前）': pct(rows[c]['B_X']),
                                         '記録の業種の分': pct(rows[c]['B_rec']), '経費率': pct(rows[c]['er_vehicle']),
                                         'NISA で戻らない配当の税': pct(rows[c]['tax_drag']), '費用の後（物差しに入る値）': pct(rows[c]['B']),
                                         '中身の業種（上位）': rows[c].get('top_industries')} for c in ('FBT', 'XLV')}
    out['式'] = 'B＝UBS の先進国株の100年（R_EQ %.2f%%）＋ 0.5×業種の100年の上乗せ ＋ 記録の業種の分 − 費用' % (100 * U.R.R_EQ)
    m100 = [m for m in allm if m >= 192701]
    out['100年の写しの単体（1927〜）'] = {nm: {**stats(s, [m for m in m100 if m in s]), '30年の積立（起点1965〜1995）の市場との比': dca(s, range(1965, 1996), 360, allm[-1])}
                                    for nm, s in ser.items()}
    mc = [m for m in allm if m >= 198601 and m in fb and all(m in x for x in ser.values())]
    both = dict(ser, **{'FBIOX（実物のバイオ投信・Fidelity Select Biotechnology・費用込み・運用者が選ぶ）': fb})
    out['同じ期間（バイオの一番長い実物の記録と）'] = {nm: {**stats(s, mc), '20年の積立（起点1985〜2006）の市場との比': dca(s, range(1985, 2007), 240, mc[-1])}
                                         for nm, s in both.items()}
    Lc = np.log1p(np.array([[ser['医薬品 Drugs（FBT の100年の写し）'][m] for m in mc], [fb[m] for m in mc]]))
    out['相関（医薬品業種と FBIOX・同じ期間）'] = round(float(np.corrcoef(Lc)[0, 1]), 3)
    try:
        el = json.load(open(os.path.join(BASE, 'out', 'etf_longest.json')))
        keep = ('name', 'kind', 'start', 'years', 'cagr', 'bench', 'excess', 'max_dd', 'underwater_yrs', 'dca20_win', 'dca20_ratio_med', 'dca20_ratio_min')
        out['etf_longest の写し（S&P500＝VFINX と同じ窓）'] = {'generated': el.get('generated'),
                                                       **{t: {k: el['rows'][t].get(k) for k in keep} for t in ('FSPHX', 'VGHCX', 'FBIOX', 'BBH', 'IBB', 'FBT', 'XLV') if t in el['rows']}}
    except Exception as x:  # noqa
        out['etf_longest の写し（S&P500＝VFINX と同じ窓）'] = f'読めず: {x}'
    return out


def pct(x, d=2):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(100 * x, d)


def main():
    t0 = time.time()
    import unx_assets as U
    import best15_check as B
    import ndx_swap_check as N
    import upside_check as UC
    import bestpf_check as BC
    import etf_forward_combo as CB
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    R = U.R
    B.century_extend(U)
    fast = B.Fast(U, rows, chains, POOL)
    cent = B.Cent(U, POOL)
    PT = Parts(fast)
    pi = fast.pi
    allf = {}
    for nm, f in FORMS.items():
        allf[nm] = f
        allf[nm + '｜XLV 版'] = swap(f)
    allf['今'] = dict(B.NOW)
    names = list(allf)
    W = np.array([[allf[k].get(c, 0) for c in POOL] for k in names], dtype=np.float64)
    e, ce = fast.eval(W), cent.eval(W)

    # 自己検問: 部品から組み直した値が Fast と一致する
    worst = 0.0
    for i, nm in enumerate(names):
        m = PT.metric(PT.ingred(allf[nm]))
        for k, kk in (('P15', 'P15'), ('P5', 'P5'), ('mean', 'mean_pi')):
            worst = max(worst, abs(m[k] - float(e[kk][i])))
    if worst > 1e-12:
        raise SystemExit(f'部品から組み直した値が best15_check.Fast と合わない（最大の差 {worst}）')
    log('自己検問 一致（最大の差', worst, '）')

    # 感度5本（ndx_swap_check.variants）
    k4, _ = N.chips_adj(rows, sorted({a for f in allf.values() for a in f} | {'VOO'}))
    vt = N.variants(allf, rows, chains, k4)[UC.W_CRASH]

    out_forms = {}
    noA2 = {k: (0.0 if k == 'A2' else v) for k, v in pi.items()}
    fwd = {k: (0.0 if k in ('A1', 'A2') else v) for k, v in pi.items()}
    for nm, f in FORMS.items():
        g = swap(f)
        ia, ib = PT.ingred(f), PT.ingred(g)
        ma, mb = PT.metric(ia), PT.metric(ib)
        sh = {key: PT.shapley(ib, ia, key) for key in ('P15', 'P5', 'mean')}
        sens = {}
        for lab, kw in (('分散の上乗せなし', dict(nobonus=True)), ('A2を外す', dict(p=noA2)), ('未来の世界だけ（B・C・D）', dict(p=fwd)),
                        ('未来の世界だけ・分散の上乗せなし', dict(p=fwd, nobonus=True))):
            xa, xb = PT.metric(ia, **kw), PT.metric(ib, **kw)
            sens[lab] = {'P15π': [pct(xb['P15']), pct(xa['P15'])], 'P5π': [pct(xb['P5']), pct(xa['P5'])], '平均': [pct(xb['mean']), pct(xa['mean'])]}
        v5 = {N.VARS_JA[v]: {'P15π': [pct(vt[nm + '｜XLV 版'][v]['P15']), pct(vt[nm][v]['P15'])],
                             '平均': [pct(vt[nm + '｜XLV 版'][v]['mean_pi'], 3), pct(vt[nm][v]['mean_pi'], 3)]} for v in N.VARS}
        ia_i, ib_i = names.index(nm), names.index(nm + '｜XLV 版')
        out_forms[nm] = {
            '形（FBT 入り）': f, 'XLV 版': g,
            '15%以上の確率（XLV 版→FBT 入り）': [pct(mb['P15']), pct(ma['P15'])],
            '5%未満の確率': [pct(mb['P5']), pct(ma['P5'])],
            'π加重の平均の年率': [pct(mb['mean']), pct(ma['mean'])],
            'ぶれ σ（道の表）': [pct(ib['sig']), pct(ia['sig'])],
            '分散の上乗せ（pt）': [pct(ib['bonus']), pct(ia['bonus'])],
            '最大下落（2000-09〜）': [pct(ib['mdd'], 1), pct(ia['mdd'], 1)],
            '過去の転がる20年で15%以上': [pct(float(e['past20'][ib_i]), 1), pct(float(e['past20'][ia_i]), 1)],
            '100年の代用 30年の積立の比（中央・最悪）': [[round(float(ce['c30med'][ib_i]), 3), round(float(ce['c30min'][ib_i]), 3)],
                                        [round(float(ce['c30med'][ia_i]), 3), round(float(ce['c30min'][ia_i]), 3)]],
            '世界ごと': {k: {'π': pi[k], '年率': [pct(mb['wv'][k]), pct(ma['wv'][k])],
                           '15%以上': [pct(mb['per15'][k], 1), pct(ma['per15'][k], 1)], '5%未満': [pct(mb['per5'][k], 1), pct(ma['per5'][k], 1)],
                           **({'予想そのもの（上乗せの前）': [pct(math.expm1(ib['raw'][k])), pct(math.expm1(ia['raw'][k]))]} if k in ('B', 'C', 'D') else {})}
                       for k in fast.E.WORLDS},
            'Shapley の寄与（pt）': {key: {**{FACT_JA[x]: round(100 * v, 2) for x, v in ph.items()}, '合計': round(100 * sum(ph.values()), 2)}
                                for key, ph in (('15%以上', sh['P15']), ('5%未満', sh['P5']), ('平均の年率', sh['mean']))},
            '感度（この道具の部品で）': sens,
            '感度5本（ndx_swap_check.variants・XLV 版→FBT 入り）': v5,
        }
        log(nm, '15%以上', out_forms[nm]['15%以上の確率（XLV 版→FBT 入り）'], 'Shapley', out_forms[nm]['Shapley の寄与（pt）']['15%以上'])

    # 道の表の例: 同じ年率でぶれだけ変える（②の世界 B と A2 の年率で）
    ex = {}
    ib2 = PT.ingred(swap(FORMS['②（勧め）SMH40/FBT30/ITA15/NASDAQ100 15']))
    ia2 = PT.ingred(FORMS['②（勧め）SMH40/FBT30/ITA15/NASDAQ100 15'])
    for lab, r in (('年率 9.16%（②の世界 B）', PT.worlds(ib2)['B']), ('年率 22.0%（②の XLV 版の世界 A2）', PT.worlds(ib2)['A2'])):
        row = {}
        for s in (0.14, 0.18, ib2['sig'], ia2['sig'], 0.26):
            try:
                row[f'σ {100 * s:.1f}%'] = {'15%以上': pct(PT.prob(math.log1p(r), s, 0.15), 1), '5%未満': pct(PT.prob(math.log1p(r), s, 0.05), 1)}
            except Exception as x:  # noqa
                row[f'σ {100 * s:.1f}%'] = f'表の外: {x}'
        ex[lab] = row

    # 単体
    i_of = {c: POOL.index(c) for c in POOL}
    Lg = np.log1p(fast.G1)
    Cr = np.corrcoef(Lg)
    single = {}
    for c in ('FBT', 'XLV', 'SMH', 'QQQM', 'ITA', 'GDX'):
        i = i_of[c]
        ps = CB.path_stats(fast.G1[i][None, :], fast.T1)
        single[c] = {'A1 直近26年': pct(rows[c]['A1']), 'A2 直近15年': pct(float(np.expm1(np.log1p(fast.G2[i]).sum() * 12 / fast.T2)) + float(fast.adj[i])),
                     'B': pct(rows[c]['B']), 'C': pct(rows[c]['C']), 'D': pct(float(np.expm1(fast.lD[i]))),
                     'ぶれ': pct(math.sqrt(fast.S1[i, i]), 1), '最大下落': pct(float(ps[2][0]), 1),
                     '相関': {d: round(float(Cr[i, i_of[d]]), 2) for d in ('SMH', 'QQQM', 'ITA', 'XLV', 'FBT') if d != c}}

    def geo(c, m0, m1):
        ks = R.months(m0, m1)
        x = np.array([chains[c][m] for m in ks])
        return float(np.expm1(np.log1p(x).sum() * 12 / len(ks)))
    periods = {}
    for m0, m1, lab in ((200009, 200605, '2000-09〜2006-05（FBT は自分の記録の前＝NYSE Arca Biotech の指数か FBIOX から費用を引いた代わり）'),
                        (200606, 201109, '2006-06〜2011-09'), (201110, 201507, '2011-10〜2015-07（バイオの上げ）'),
                        (201508, 202609, '2015-08〜2026-09'), (201601, 202609, '2016-01〜2026-09'),
                        (201110, 202609, 'A2 の窓 2011-10〜2026-09'), (200009, 202609, 'A1 の窓 2000-09〜2026-09')):
        periods[lab] = {'FBT': pct(geo('FBT', m0, m1)), 'XLV': pct(geo('XLV', m0, m1))}
    years = {}
    for y in range(2001, 2026):
        ks = R.months(y * 100 + 1, y * 100 + 12)
        a = float(np.prod([1 + chains['FBT'][m] for m in ks]) - 1)
        b = float(np.prod([1 + chains['XLV'][m] for m in ks]) - 1)
        years[str(y)] = {'FBT': pct(a, 1), 'XLV': pct(b, 1), '差': pct(a - b, 1)}

    doc = dict(generated=time.strftime('%Y-%m-%d'), tool='night/best15_fbt_why.py', kind='参考・判定なし（配分は変えない）',
               question='なぜFBTだとあがるの？？（best15 の形で FBT が15%以上の確率を上げる理由）', pi=pi,
               部品=FACT_JA, 形=out_forms, 道の表の例=ex, 単体=single, 期間ごとの年率=periods, 暦年=years,
               FBTが上の年=sum(1 for v in years.values() if v['差'] > 0), 年の数=len(years))

    # 事後（判定に使わない）: XLV 版を best15 の T1 の物差しと最終の確かめで今と比べる
    now_i = names.index('今')
    now = {k: float(v[now_i]) for k, v in {**e, **ce}.items() if k != 'ok'}
    post = {}
    xlv_forms = {nm + '｜XLV 版': swap(f) for nm, f in FORMS.items() if not nm.startswith('今')}
    ch_jpy, _ = U.jpy_chains(chains)
    fc, _, _ = B.final_check(U, N, rows, chains, ch_jpy, xlv_forms, 'T1')
    for nm in xlv_forms:
        i = names.index(nm)
        ei = {k: np.array([float(v[i])]) for k, v in e.items() if k != 'ok'}
        ci = dict(ok=np.array([bool(ce['ok'][i])]), c30med=np.array([float(ce['c30med'][i])]), c30min=np.array([float(ce['c30min'][i])]))
        g = B.gates(ei, ci, now, 'T1')
        post[nm] = {'形': xlv_forms[nm], 'T1 の8つの物差しで今を下回らない': {k: bool(v[0]) for k, v in g.items()},
                    '今との差（15%以上・pt）': pct(float(e['P15'][i]) - now['P15']), '今との差（5%未満・pt）': pct(float(e['P5'][i]) - now['P5']),
                    '今との差（平均・pt）': pct(float(e['mean_pi'][i]) - now['mean_pi'], 3), '最大下落': [pct(now['mdd'], 1), pct(float(e['mdd'][i]), 1)],
                    '過去の20年で15%以上': [pct(now['past20'], 1), pct(float(e['past20'][i]), 1)],
                    '100年の代用（中央・最悪）': [[round(now['c30med'], 3), round(now['c30min'], 3)], [round(float(ce['c30med'][i]), 3), round(float(ce['c30min'][i]), 3)]],
                    'F1 感度5本': fc[nm]['F1の合否'], 'F2 円の枠': fc[nm]['F2の合否'], '感度ごとの差': fc[nm]['感度ごとの差'], '円の枠': fc[nm]['円の枠']}
    doc['事後（判定に使わない）XLV 版を今と比べる'] = post
    doc['今'] = {'形': dict(B.NOW), '15%以上': pct(now['P15']), '5%未満': pct(now['P5']), '平均': pct(now['mean_pi']), '最大下落': pct(now['mdd'], 1),
                 '過去の20年で15%以上': pct(now['past20'], 1), '100年の代用（中央・最悪）': [round(now['c30med'], 3), round(now['c30min'], 3)]}
    doc['長い記録（判定に使わない）'] = long_record(U, res, rows)
    doc['secs'] = round(time.time() - t0)
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    log('完了', doc['secs'], '秒 →', OUT)


if __name__ == '__main__':
    main()
